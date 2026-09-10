import QtQuick
import QtQuick.Controls.Basic

/* The outcome of one distribution pass, as coloured pills — the roster table's Distribution
   column and the batch journal draw the same thing, so they draw it from here.

   Actions the pass did not run are skipped, and an empty map renders a dash rather than an
   empty cell: "nothing recorded yet" and "recorded nothing" must not look alike. */
Row {
    id: root
    property var outcomes: ({})
    property bool compact: false
    readonly property var recorded: DistActions.recorded(root.outcomes)

    spacing: 4

    Text {
        visible: root.recorded.length === 0
        anchors.verticalCenter: parent.verticalCenter
        text: "—"
        color: Theme.muted
        font.pixelSize: 13
    }

    Repeater {
        model: root.recorded
        delegate: Chip {
            required property var modelData
            readonly property string outcome: root.outcomes[modelData.journal] || ""
            anchors.verticalCenter: parent.verticalCenter
            text: root.compact ? i18n.t(modelData.label).slice(0, 1) : i18n.t(modelData.label)
            fg: Theme.outcomeInk(outcome)
            bg: Theme.outcomeSoft(outcome)

            HoverHandler { id: hov }
            ToolTip.visible: hov.hovered
            ToolTip.text: i18n.t(modelData.label) + " · " + i18n.t(DistActions.outcomeLabel(outcome))
            ToolTip.delay: 350
        }
    }
}
