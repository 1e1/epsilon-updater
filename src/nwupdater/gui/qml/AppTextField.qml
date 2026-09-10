import QtQuick
import QtQuick.Controls.Basic

/* The text field the Basic style does not give us. Its default background is a square 40 px
   rectangle painted from the *system* palette, so a raw TextField ignores Theme entirely and
   stays light when the window is switched to dark. Here the tokens rule, as everywhere else.

   Two sizes, taken from the web UI: the default matches AppButton's 30 px so a field and a
   button sit on the same line, `compact` is the in-table one (the roster filter lives inside a
   44 px header row). */
TextField {
    id: control
    property bool compact: false

    padding: 6
    leftPadding: padding + 4
    rightPadding: padding + 4
    font.pixelSize: control.compact ? 12 : 13
    color: Theme.ink
    placeholderTextColor: Theme.muted
    selectionColor: Theme.accentSoft
    selectedTextColor: Theme.ink

    background: Rectangle {
        implicitWidth: 160
        implicitHeight: control.compact ? 28 : 30
        radius: control.compact ? 8 : 9
        color: Theme.card
        border.width: 1
        border.color: control.activeFocus ? Theme.accent : Theme.lineStrong
        Behavior on border.color { ColorAnimation { duration: 90 } }
    }
}
