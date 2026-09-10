pragma Singleton
import QtQuick

/* The distribution chain, once.

   Three names for the same four steps used to live in three files: the config keys in
   `roster.py`, a glyph+label table in DistributionPane, and a second label table in
   BatchWindow. They also disagree on one point that is easy to get wrong — the first step is
   CONFIGURED as `census` but RECORDED in the journal as `recensement` (see Session.batch_run),
   so a lookup by the wrong name silently renders nothing. Both names live here, side by side. */
QtObject {
    readonly property var chain: [
        { key: "census",   journal: "recensement", glyph: "▤", label: "roster_dist_recensement" },
        { key: "firmware", journal: "firmware",    glyph: "⚙", label: "roster_dist_firmware" },
        { key: "apps",     journal: "apps",        glyph: "▦", label: "roster_dist_apps" },
        { key: "scripts",  journal: "scripts",     glyph: "‹›", label: "roster_dist_scripts" }
    ]

    /* The i18n key naming an outcome ("conforme" / "modifié" / "erreur"). */
    function outcomeLabel(o) {
        return o === "ok" ? "roster_dist_ok"
             : o === "change" ? "roster_dist_change"
             : o === "error" ? "roster_dist_error" : ""
    }

    /* The steps of a recorded pass, in chain order, skipping the ones it did not run. */
    function recorded(dist) {
        if (!dist)
            return []
        return chain.filter((a) => ["ok", "change", "error"].indexOf(dist[a.journal]) >= 0)
    }
}
