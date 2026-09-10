pragma Singleton
import QtQuick

/* The web UI's design tokens, verbatim (index.html :root). Kept deliberately instead of the
   platform styles (macOS / FluentWinUI3): the palette is the product's identity — the native
   part of this port is the chrome and the behaviour, not the look. */
QtObject {
    id: t
    property bool dark: false

    readonly property color desk:       dark ? "#0d0e11" : "#e4e2db"
    readonly property color bg:         dark ? "#141519" : "#edece7"
    readonly property color panel:      dark ? "#191b20" : "#f6f4ef"
    readonly property color card:       dark ? "#1f2228" : "#ffffff"
    readonly property color chrome:     dark ? "#1c1e24" : "#f1efe9"
    readonly property color ink:        dark ? "#eceef1" : "#1b1c1e"
    readonly property color muted:      dark ? "#969aa2" : "#6d6f74"
    readonly property color line:       dark ? "#2a2d34" : "#e6e3dc"
    readonly property color lineStrong: dark ? "#363a42" : "#d8d4ca"
    readonly property color accent:     dark ? "#f7b53d" : "#e8930c"
    readonly property color accentSoft: dark ? "#3a2e14" : "#fbe9cd"
    readonly property color accentInk:  dark ? "#f7c469" : "#7a4d05"
    readonly property color ok:         dark ? "#3fbd77" : "#1f9d57"
    readonly property color okSoft:     dark ? "#16301f" : "#dcf1e5"
    readonly property color err:        dark ? "#e26a6a" : "#d64545"
    readonly property color errSoft:    dark ? "#3a1c1c" : "#fbe0e0"
    readonly property color blue:       dark ? "#6f9bff" : "#3d68c9"
    readonly property color blueSoft:   dark ? "#1b2740" : "#e2ecfd"
    // what sits ON a filled accent: the accent is dark in the light theme and light in
    // the dark one, so the ink has to flip with it (a tick, a badge label).
    readonly property color onAccent:   dark ? "#151619" : "#ffffff"

    readonly property int radius: 12
    readonly property string sans: Qt.platform.os === "windows" ? "Segoe UI" : ""
    readonly property string mono: Qt.platform.os === "windows" ? "Consolas" : "Menlo"

    /* Write-plan status → colours. `statusColor` paints the solid marks (the row stripe, a
       memory-bar segment); the ink/soft pair is the chip that names the status. */
    function statusColor(s) {
        return s === "un" ? ok : s === "rw" ? accent : s === "new" ? blue : lineStrong
    }
    function statusInk(s) {
        return s === "un" ? ok : s === "new" ? blue : accentInk
    }
    function statusSoft(s) {
        return s === "un" ? okSoft : s === "new" ? blueSoft : accentSoft
    }

    /* Batch outcome → colours, shared by the roster's distribution column and the batch
       journal. `error` gets the error token, not a stand-in from another family. */
    function outcomeInk(o) {
        return o === "ok" ? ok : o === "change" ? accent : o === "error" ? err : muted
    }
    function outcomeSoft(o) {
        return o === "ok" ? okSoft : o === "change" ? accentSoft : o === "error" ? errSoft : panel
    }
}
