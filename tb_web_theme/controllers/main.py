# Part of tobias. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.http import request

ICON_PARAM = 'tb_web_theme.icon_attachment_id'
LOGIN_BG_PARAM = 'tb_web_theme.login_bg_attachment_id'

ICON_FALLBACK = '/tb_web_theme/static/src/img/tobia_logo.png'


class TbThemeController(http.Controller):

    @http.route('/tb_theme/icon', type='http', auth='public', sitemap=False)
    def tb_theme_icon(self):
        """Brand mark uploaded in General Settings (tab icon, top bar, login)."""
        response = self._theme_image_response(ICON_PARAM)
        return response or request.redirect(ICON_FALLBACK)

    @http.route('/tb_theme/login-bg', type='http', auth='public', sitemap=False)
    def tb_theme_login_bg(self):
        """Login page background uploaded in General Settings."""
        return self._theme_image_response(LOGIN_BG_PARAM) or request.not_found()

    def _theme_image_response(self, param):
        attachment_id = request.env['ir.config_parameter'].sudo().get_int(param, 0)
        if not attachment_id:
            return None
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id).exists()
        if not attachment:
            return None
        content = bytes(attachment.raw)
        return request.make_response(content, headers=[
            ('Content-Type', attachment.mimetype or 'application/octet-stream'),
            ('Content-Length', str(len(content))),
            ('Cache-Control', 'no-store, max-age=0'),
        ])
