import QtQuick

/* Main area with nothing plugged in. The rail carries the actions; this only says why the
   pane is empty. */
Item {
    Column {
        anchors.centerIn: parent
        spacing: 8
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "🔌"
            font.pixelSize: 34
            opacity: 0.7
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: i18n.t("nodev_title")
            color: Theme.muted
            font.pixelSize: 13
        }
    }
}
