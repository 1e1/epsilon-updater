import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

/* Left rail, individual mode: the connected calculator. */
ColumnLayout {
    id: root
    property var identity: ({})
    property var deviceName: ({})
    spacing: 12

    // The name sits on the panel, not in a box: only focus gives it a frame. Everything else
    // (placeholder, selection, caret) comes from AppTextField, i.e. from Theme — a raw
    // TextField would keep drawing those from the system palette in the dark theme.
    AppTextField {
        id: nameField
        Layout.fillWidth: true
        Layout.topMargin: 4
        text: root.deviceName.name || ""
        placeholderText: root.deviceName.default || ""
        horizontalAlignment: TextInput.AlignHCenter
        font.pixelSize: 15
        font.weight: Font.DemiBold
        background: Rectangle {
            radius: 8
            color: nameField.activeFocus ? Theme.card : "transparent"
            border.width: nameField.activeFocus ? 1 : 0
            border.color: Theme.lineStrong
        }
        onEditingFinished: backend.setDeviceName(nameField.text)
        Keys.onEscapePressed: { nameField.text = root.deviceName.name || ""; nameField.focus = false }
    }

    Image {
        Layout.alignment: Qt.AlignHCenter
        source: "../assets/calc-" + (root.identity.family === "scientifique" ? "scientific" : "graphing")
                + "-device.svg"
        sourceSize.width: 150
        fillMode: Image.PreserveAspectFit
        smooth: true
    }

    // One row per fact. The KEY yields width, never the value: an elided OS version or MCU is
    // useless, so only the serial (long, and masked anyway) is allowed to shorten.
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 9

        SpecRow {
            label: i18n.t("model")
            SpecVal { text: root.identity.model || "—"; font.family: Theme.mono }
            Chip { visible: !!root.identity.virtual; text: i18n.t("demo_tag") }
        }
        SpecRow {
            label: i18n.t("family")
            Chip {
                text: root.identity.family === "scientifique" ? i18n.t("fam_s") : i18n.t("fam_g")
            }
        }
        SpecRow {
            label: "MCU"
            SpecVal { text: root.identity.mcu || "—"; font.family: Theme.mono }
        }
        SpecRow {
            label: i18n.t("serial")
            SpecVal {
                id: serial
                property bool shown: false
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                horizontalAlignment: Text.AlignRight
                text: root.identity.serial_number || "—"
                font.family: Theme.mono
                font.pixelSize: 12
                elide: Text.ElideMiddle
                opacity: shown ? 1 : 0.25
                TapHandler { onTapped: serial.shown = !serial.shown }
                HoverHandler { id: serialHover; cursorShape: Qt.PointingHandCursor }
                ToolTip.visible: serialHover.hovered
                ToolTip.text: i18n.t("serial_reveal")
            }
        }
        SpecRow {
            label: "OS"
            SpecVal { text: "Epsilon " + (root.identity.os_version || "?"); font.family: Theme.mono }
        }
        SpecRow {
            label: i18n.t("appsregion")
            Text {
                text: root.identity.has_external_apps ? "✓" : "—"
                color: root.identity.has_external_apps ? Theme.ok : Theme.muted
                font.pixelSize: 13
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: !!root.identity.virtual
        spacing: 8
        SpecKey { text: i18n.t("demo_model") }
        AppComboBox {
            Layout.fillWidth: true
            Layout.preferredWidth: 0
            model: backend.demoModels
            currentIndex: Math.max(0, backend.demoModels.indexOf(root.identity.model))
            font.pixelSize: 12
            onActivated: (i) => backend.exploreDemo(backend.demoModels[i])
        }
    }

    Item { Layout.fillHeight: true }

    AppButton {
        Layout.fillWidth: true
        ghost: true
        text: i18n.t("dev_menu")
        onClicked: backend.detach()
    }
}
