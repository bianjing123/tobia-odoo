# Part of tobias. See LICENSE file for full copyright and licensing details.

from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _post_logout(cls):
        super()._post_logout()
        request.future_response.set_cookie('color_scheme', max_age=0)

    def color_scheme(self):
        """Cookie-based color scheme (Odoo community core hardcodes "light").

        The systray toggle writes the ``color_scheme`` cookie then reloads;
        ``web.webclient_bootstrap`` renders ``web.assets_web_dark`` instead of
        ``web.assets_web`` when this returns "dark".
        """
        cookie_scheme = request.httprequest.cookies.get('color_scheme')
        if cookie_scheme in ('light', 'dark'):
            return cookie_scheme
        return super().color_scheme()
