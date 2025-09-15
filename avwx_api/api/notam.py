"""NOTAM API Routes."""

from avwx.exceptions import InvalidRequest
from avwx_api_core.token import Token
from quart import Response
from quart_openapi.cors import crossdomain

from avwx_api import app, structs, validate
from avwx_api.api.base import HEADERS, Base, Parse, Report, parse_params, token_check
from avwx_api.handle.notam import NotamDBHandler


@app.route("/api/notam/<location>")
class NotamSearch(Report):
    """Search for current NOTAMs in the database."""

    report_type = "notam"
    loc_param = "location"
    plan_types = ("enterprise",)
    validator = validate.notam_location
    struct = structs.NotamLocation
    handler = NotamDBHandler()
    key_remv = ("remarks",)


@app.route("/api/parse/notam")
class NotamParse(Parse):
    report_type = "notam"
    loc_param = "location"
    plan_types = ("enterprise",)
    handler = NotamDBHandler()
    key_remv = ("remarks",)


@app.route("/api/path/notam")
class NotamAlong(Base):
    """Returns NOTAMs along a flight path"""

    validator = validate.notam_along
    struct = structs.NotamRoute
    handler: NotamDBHandler = NotamDBHandler()
    key_remv = ("remarks",)
    example = "notam_along"
    plan_types = ("enterprise",)

    @crossdomain(origin="*", headers=HEADERS)
    @parse_params
    @token_check
    async def get(self, params: structs.NotamRoute, token: Token | None) -> Response:
        """Returns reports along a flight path"""
        config = structs.ParseConfig.from_params(params, token)
        try:
            reports, _ = await self.handler.fetch_along(params.route, config.distance or 10, config)
        except InvalidRequest as exc:
            error_resp = {"error": f"Search criteria appears to be invalid: {exc.args[0]}"}
            return self.make_response(error_resp, params, 400)
        resp = {
            "meta": self.handler.make_meta(),
            "route": params.route,
            "results": reports["data"],
        }
        return self.make_response(resp, params)
