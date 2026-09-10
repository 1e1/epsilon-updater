import QtQuick
import QtQuick.Layouts

/* Left rail with nothing plugged in: rescan, or explore a demo model. */
ColumnLayout {
    id: root
    spacing: 10

    Item { Layout.fillHeight: true }
    Text {
        Layout.alignment: Qt.AlignHCenter
        text: "🔌"
        font.pixelSize: 30
    }
    Text {
        Layout.fillWidth: true
        text: i18n.t("nodev_title")
        color: Theme.muted
        font.pixelSize: 12
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
    }
    AppButton {
        Layout.fillWidth: true
        text: i18n.t("rescan")
        enabled: backend.busy === ""
        onClicked: backend.rescan()
    }
    // `demoModels` is a list of plain strings, so no textRole: setting one made every entry
    // render empty and handed `undefined` to exploreDemo — the demo picker on the very first
    // screen did nothing at all.
    AppComboBox {
        id: demoPick
        Layout.fillWidth: true
        model: backend.demoModels
        font.pixelSize: 12
    }
    AppButton {
        Layout.fillWidth: true
        ghost: true
        text: i18n.t("demo_btn")
        enabled: backend.busy === ""
        onClicked: backend.exploreDemo(backend.demoModels[demoPick.currentIndex])
    }
    Item { Layout.fillHeight: true }
}
