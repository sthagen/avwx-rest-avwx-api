"""NOTAM handling during FAA ICAO format migration."""

import json
from http import HTTPStatus

import avwx
import shapely
from avwx.static.core import IN_UNITS
from avwx.structs import Coord, Units

from avwx_api.app_config import app
from avwx_api.handle.base import ListedReportHandler
from avwx_api.structs import DataStatus, ParseConfig


def nautical_miles_to_degrees(nm: float) -> float:
    """Convert nautical miles to degrees of latitude (1 NM = 1/60 degree)."""
    return nm / 60.0


def nautical_miles_to_meters(nm: float) -> float:
    """Convert nautical miles to meters (1 NM = 1852 meters)."""
    return nm * 1852.0


def route_to_shape(route: list[Coord], distance: int) -> dict:
    """Convert a list of coordinates to a GeoJSON shape buffered by distance in nautical miles"""
    line = shapely.LineString([(c.lon, c.lat) for c in route])
    buffered = shapely.buffer(line, nautical_miles_to_degrees(distance))
    shape: dict = json.loads(shapely.to_geojson(buffered))
    return shape


def radius_search(lat: float, lon: float, distance: int) -> dict:
    """Returns a MongoDB geospatial search for a point and distance in nautical miles."""
    return {
        "point": {
            "$nearSphere": {
                "$geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "$maxDistance": nautical_miles_to_meters(distance),
            }
        }
    }


def intersect_search(shape: dict) -> dict:
    """Returns a MongoDB geospatial search for a point within a polygon."""
    return {"location": {"$geoIntersects": {"$geometry": shape}}}


def contains_search(lat: float, lon: float) -> dict:
    """Returns a MongoDB geospatial search for a point within a polygon."""
    if lat is None or lon is None:
        msg = "Must provide lat and lon"
        raise ValueError(msg)
    return intersect_search(
        {
            "type": "Point",
            "coordinates": [lon, lat],
        }
    )


def route_search(route: list[Coord], distance: int) -> dict:
    """Returns a MongoDB geospatial search for a route buffered by distance in nautical miles."""
    if len(route) < 2:
        msg = "Route must have at least two waypoints"
        raise ValueError(msg)
    return intersect_search(route_to_shape(route, distance))


class NotamDBHandler(ListedReportHandler):
    """Handler to fetch NOTAMs from the database."""

    report_type = "notam"
    parser = avwx.Notams
    cache = False

    async def fetch_report(
        self,
        loc: avwx.Station | Coord,
        config: ParseConfig,
    ) -> DataStatus:
        """Fetches NOTAMs for a location and config."""
        searches: tuple[dict, ...]
        if isinstance(loc, avwx.Station):
            searches = ({"station": loc.lookup_code},)
        else:
            searches = (
                radius_search(loc.lat, loc.lon, config.distance or 10),
                contains_search(loc.lat, loc.lon),
            )
        reports: dict[str, dict] = {}
        for search in searches:
            async for notam in app.mdb.report.notam.find(search):
                reports[notam["_id"]] = notam["data"]
        # copy necessary functionality of _post_handle here
        resp = {"data": list(reports.values()), "units": Units(**IN_UNITS)}
        return await self._post_handle(
            resp, HTTPStatus.OK, None, loc if isinstance(loc, avwx.Station) else None, config
        )

    async def fetch_along(self, route: list[Coord], distance: int, config: ParseConfig) -> DataStatus:
        """Fetches NOTAMs along a route within a distance in nautical miles."""
        if len(route) < 2:
            return {"error": "Route must have at least two waypoints"}, HTTPStatus.BAD_REQUEST
        search = route_search(route, distance or 10)
        reports: dict[str, dict] = {}
        async for notam in app.mdb.report.notam.find(search):
            reports[notam["_id"]] = notam["data"]
        resp = {"data": list(reports.values()), "units": Units(**IN_UNITS)}
        return await self._post_handle(resp, HTTPStatus.OK, None, None, config)
