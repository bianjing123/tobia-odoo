import { loadBundle } from "@web/core/assets";

/**
 * Chart.js draws axis / legend / tooltip labels on a canvas, so they cannot be
 * reached from the SCSS type scale.
 *
 * The graph renderer module lives in its own lazy view bundle, so it must not
 * be imported from the backend bundle (doing so breaks asset loading). Load the
 * chart.js bundle directly instead and patch its defaults once: the promise is
 * cached, so every chart created afterwards (graph view, dashboards) renders
 * its labels at 13px like the rest of the UI.
 */
const FONT_SIZE = 13;

loadBundle("web.chartjs_lib").then(() => {
    if (window.Chart?.defaults?.font) {
        window.Chart.defaults.font.size = FONT_SIZE;
    }
});
