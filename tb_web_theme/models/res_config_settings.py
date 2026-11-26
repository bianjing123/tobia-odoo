# Part of tobias. See LICENSE file for full copyright and licensing details.

from odoo import fields, models

ICON_PARAM = 'tb_web_theme.icon_attachment_id'
LOGIN_BG_PARAM = 'tb_web_theme.login_bg_attachment_id'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # attachment=False: the uploaded file reaches set_values() as-is, so it can
    # be copied into a standalone ir.attachment (transient records are vacuumed)
    tb_theme_icon = fields.Binary(string="Small Icon", attachment=False)
    tb_theme_login_bg = fields.Binary(string="Login Page Background", attachment=False)

    def get_values(self):
        res = super().get_values()
        res['tb_theme_icon'] = self._tb_theme_attachment_base64(ICON_PARAM)
        res['tb_theme_login_bg'] = self._tb_theme_attachment_base64(LOGIN_BG_PARAM)
        return res

    def set_values(self):
        super().set_values()
        self._tb_theme_store_attachment('tb_theme_icon', ICON_PARAM, 'tobia-theme-icon')
        self._tb_theme_store_attachment('tb_theme_login_bg', LOGIN_BG_PARAM, 'tobia-login-background')

    def _tb_theme_attachment(self, param):
        attachment_id = self.env['ir.config_parameter'].sudo().get_int(param, 0)
        if not attachment_id:
            return self.env['ir.attachment']
        return self.env['ir.attachment'].sudo().browse(attachment_id).exists()

    def _tb_theme_attachment_base64(self, param):
        attachment = self._tb_theme_attachment(param)
        return attachment.raw.to_base64() if attachment else False

    def _tb_theme_store_attachment(self, field_name, param, default_name):
        attachment = self._tb_theme_attachment(param)
        value = self[field_name]
        params = self.env['ir.config_parameter'].sudo()

        if not value:
            if attachment:
                attachment.unlink()
            # False (not 0) so that the parameter is unset instead of "0"
            params.set_int(param, False)
            return

        datas = value.to_base64()
        # save/apply without touching the file keeps the current attachment
        if attachment and attachment.raw.to_base64() == datas:
            return

        mimetype = value.mimetype or 'image/png'
        # Odoo 20 only honours ``raw`` on ir.attachment (``datas`` is ignored)
        vals = {
            'name': '%s.%s' % (default_name, mimetype.rsplit('/', 1)[-1].replace('svg+xml', 'svg')),
            'raw': value.content,
            'mimetype': mimetype,
        }
        if attachment:
            attachment.write(vals)
        else:
            attachment = self.env['ir.attachment'].sudo().create(vals)
            params.set_int(param, attachment.id)
