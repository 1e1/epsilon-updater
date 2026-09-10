import QtQuick
import QtQuick.Layouts

/* The always-there status line. Kept even though the OS has notifications: a notification can
   be silenced system-wide, this cannot.

   It holds the message as an i18n KEY plus its placeholder values, never as a rendered
   sentence. The backend emits `("fw_done", {v: "20.4.0"}, false)`, so the line reads "Firmware
   20.4.0 flashé et vérifié" — and re-reads itself in English if the language is switched while
   it is still on screen. Assigning the key straight to a Text is how it used to display
   `install_ok::20.4.0` to a teacher. */
Rectangle {
    id: root
    property string messageKey: ""
    property var messageParams: ({})
    property bool error: false
    readonly property string message: root.messageKey === ""
                                    ? "" : i18n.t(root.messageKey, root.messageParams)

    implicitHeight: 28
    color: Theme.chrome

    Rectangle { width: parent.width; height: 1; color: Theme.line }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        spacing: 10
        Rectangle {
            Layout.preferredWidth: 7
            Layout.preferredHeight: 7
            radius: 4
            color: backend.connected ? Theme.ok : Theme.muted
        }
        Text {
            text: backend.mode === "classroom" ? i18n.t("mode_classroom")
                                               : i18n.t("mode_individual")
            color: Theme.accentInk
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }
        Rectangle {
            visible: root.message !== ""
            Layout.preferredWidth: 1
            Layout.preferredHeight: 12
            color: Theme.line
        }
        Text {
            Layout.fillWidth: true
            visible: root.message !== ""
            text: root.message
            color: root.error ? Theme.err : Theme.muted
            font.pixelSize: 12
            elide: Text.ElideRight
        }
        Item { Layout.fillWidth: true; visible: root.message === "" }
        Text {
            text: i18n.t("status_local")
            color: Theme.muted
            font.pixelSize: 11
        }
        Text {
            text: "🔒  " + i18n.t("disc")
            color: Theme.muted
            font.pixelSize: 11
        }
    }

    Connections {
        target: backend
        function onToast(key, params, isError) {
            root.messageKey = key
            root.messageParams = params
            root.error = isError
            reset.restart()
        }
    }
    Timer {
        id: reset
        interval: 6000
        onTriggered: { root.messageKey = ""; root.messageParams = ({}); root.error = false }
    }
}
