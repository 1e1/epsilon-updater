import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

/* Batch kiosk: armed once for a class, then every calculator that is plugged in runs that
   class's chain. A real second window, so it can go fullscreen on a projector while the main
   window stays usable — the web version could only cover the page. */
Window {
    id: batch
    width: 980
    height: 660
    minimumWidth: 720
    minimumHeight: 480
    title: i18n.t("batch_mode") + " — nwupdater"
    color: Theme.bg

    onVisibleChanged: if (!visible) backend.disarmBatch()

    // Auto-run: a real calculator plugged in while armed runs the chain once, then waits for
    // it to be unplugged before arming the next one.
    property bool passDone: false
    Connections {
        target: backend
        function onIdentityChanged() {
            if (!backend.identity.connected) batch.passDone = false
            else if (batch.visible && !batch.passDone && !backend.identity.virtual) {
                batch.passDone = true
                backend.batchRunOnce()
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 52
            color: Theme.panel
            Rectangle { width: parent.width; height: 1; y: parent.height - 1; color: Theme.line }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 10
                Text {
                    text: i18n.t("batch_mode")
                    color: Theme.ink
                    font.pixelSize: 15
                    font.weight: Font.Bold
                }
                Chip { text: backend.batch.className }
                Item { Layout.fillWidth: true }
                AppButton {
                    danger: true
                    text: "■  " + i18n.t("batch_stop")
                    onClicked: batch.close()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // -- left: what is plugged in ------------------------------------------
            Rectangle {
                Layout.preferredWidth: 300
                Layout.fillHeight: true
                color: Theme.panel

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 12

                    Item { Layout.fillHeight: true }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: !backend.connected
                        spacing: 10
                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: "⇅"
                            color: Theme.accent
                            font.pixelSize: 40
                            SequentialAnimation on opacity {
                                running: !backend.connected
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.4; duration: 900 }
                                NumberAnimation { to: 1.0; duration: 900 }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: i18n.t("batch_waiting")
                            color: Theme.muted
                            font.pixelSize: 14
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: backend.connected
                        spacing: 10
                        Image {
                            Layout.alignment: Qt.AlignHCenter
                            source: "../assets/calc-"
                                    + (backend.identity.family === "scientifique"
                                       ? "scientific" : "graphing") + "-device.svg"
                            sourceSize.width: 150
                            fillMode: Image.PreserveAspectFit
                        }
                        SpecRow {
                            label: i18n.t("model")
                            SpecVal { text: backend.identity.model || "—"; font.family: Theme.mono }
                        }
                        SpecRow {
                            label: "OS"
                            SpecVal {
                                text: "Epsilon " + (backend.identity.os_version || "?")
                                font.family: Theme.mono
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }

                    // Demo run: the same chain, without hardware.
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: !backend.connected || backend.identity.virtual
                        spacing: 6
                        ComboBox {
                            id: simModel
                            Layout.fillWidth: true
                            font.pixelSize: 12
                            model: backend.demoModels
                        }
                        AppButton {
                            Layout.fillWidth: true
                            ghost: true
                            text: i18n.t("batch_simulate")
                            enabled: backend.busy === ""
                            onClicked: backend.batchSimulate(
                                backend.demoModels[simModel.currentIndex])
                        }
                    }
                }
            }

            Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: Theme.line }

            // -- right: what the pass does, and what it did -------------------------
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 42
                    color: Theme.accentSoft
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        spacing: 8
                        Text { text: "⚠"; color: Theme.accentInk; font.pixelSize: 14 }
                        Text {
                            Layout.fillWidth: true
                            text: i18n.t("batch_armed")
                            color: Theme.accentInk
                            font.pixelSize: 13
                            elide: Text.ElideRight
                        }
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    Layout.margins: 16
                    spacing: 6
                    Repeater {
                        model: backend.batchSteps
                        delegate: Chip {
                            required property string modelData
                            text: modelData === "census" ? i18n.t("roster_dist_recensement")
                                : modelData === "firmware" ? i18n.t("roster_dist_firmware")
                                : modelData === "apps" ? i18n.t("roster_dist_apps")
                                : i18n.t("roster_dist_scripts")
                        }
                    }
                    Chip {
                        visible: backend.batchSteps.length === 0
                        text: i18n.t("batch_no_action")
                        fg: Theme.muted
                        bg: Theme.panel
                    }
                }

                Text {
                    Layout.leftMargin: 16
                    text: i18n.t("batch_journal")
                    color: Theme.muted
                    font.pixelSize: 11
                    font.weight: Font.Bold
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 0.8
                }

                ListView {
                    id: journal
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.margins: 16
                    clip: true
                    spacing: 6
                    model: backend.batch.journal
                    ScrollBar.vertical: ScrollBar {}

                    Text {
                        anchors.centerIn: parent
                        visible: journal.count === 0
                        text: i18n.t("batch_empty")
                        color: Theme.muted
                        font.pixelSize: 13
                    }

                    delegate: Rectangle {
                        id: entry
                        required property var modelData
                        width: journal.width
                        height: 48
                        radius: 9
                        color: Theme.card
                        border.width: 1
                        border.color: Theme.line

                        function outcomeColor(o) {
                            return o === "ok" ? Theme.ok
                                 : o === "change" ? Theme.accent
                                 : o === "error" ? Theme.err : Theme.muted
                        }
                        function outcomeBg(o) {
                            return o === "ok" ? Theme.okSoft
                                 : o === "change" ? Theme.accentSoft
                                 : o === "error" ? Theme.blueSoft : Theme.panel
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 10
                            Text {
                                text: entry.modelData.name || entry.modelData.default || "—"
                                color: Theme.ink
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            Text {
                                text: entry.modelData.firmware
                                      ? "Epsilon " + entry.modelData.firmware : ""
                                color: Theme.muted
                                font.pixelSize: 12
                            }
                            Item { Layout.fillWidth: true }
                            // one chip per action of the pass, coloured by its outcome
                            Repeater {
                                model: ["recensement", "firmware", "apps", "scripts"].filter(
                                    (a) => (entry.modelData.dist || {})[a] !== undefined)
                                delegate: Chip {
                                    required property string modelData
                                    readonly property string outcome:
                                        (entry.modelData.dist || {})[modelData] || ""
                                    text: modelData
                                    fg: entry.outcomeColor(outcome)
                                    bg: entry.outcomeBg(outcome)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
