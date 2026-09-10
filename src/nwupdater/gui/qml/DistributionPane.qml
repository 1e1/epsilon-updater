import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

/* Per-class distribution, mirroring the web pane: recensement is always shown, the action
   chain is a clickable pipeline, and each action reveals its own panel only once enabled. */
Flickable {
    id: root
    readonly property var dist: backend.distribution
    readonly property var actions: dist.actions || ({})
    contentHeight: col.implicitHeight + 32
    clip: true
    ScrollBar.vertical: AppScrollBar {}

    ColumnLayout {
        id: col
        x: 16; y: 16
        width: root.width - 32
        spacing: 12

        Text {
            Layout.fillWidth: true
            visible: !root.dist.editable
            text: i18n.t("dist_pick_class")
            color: Theme.muted
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }

        // -- recensement: always visible; its wording depends on the chain ------------
        Card {
            Layout.fillWidth: true
            visible: root.dist.editable
            title: i18n.t("roster_dist_recensement")

            Text {
                Layout.fillWidth: true
                text: i18n.t("dist_census_hint")
                color: Theme.muted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
            RadioRow {
                checked: root.dist.onboarding === "move"
                text: root.actions.census
                      ? i18n.t("dist_ob_move", { c: root.dist.className })
                      : i18n.t("dist_ob_exclusive", { c: root.dist.className })
                onPicked: backend.distSetOnboarding("move")
            }
            RadioRow {
                checked: root.dist.onboarding === "ignore"
                text: i18n.t("dist_ob_ignore")
                onPicked: backend.distSetOnboarding("ignore")
            }
        }

        // -- the action chain --------------------------------------------------------
        Card {
            Layout.fillWidth: true
            visible: root.dist.editable
            title: i18n.t("dist_chain")

            Text {
                Layout.fillWidth: true
                text: i18n.t("dist_chain_hint")
                color: Theme.muted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
            Flow {
                Layout.fillWidth: true
                spacing: 6
                Repeater {
                    // The chain and its glyphs live in the DistActions singleton: this pane and
                    // the batch journal used to keep two tables of the same four steps.
                    model: DistActions.chain
                    delegate: Row {
                        id: step
                        required property var modelData
                        required property int index
                        readonly property bool on: !!root.actions[step.modelData.key]
                        spacing: 6

                        Rectangle {
                            width: node.implicitWidth + 22
                            height: 34
                            radius: 9
                            color: step.on ? Theme.accentSoft : Theme.panel
                            border.width: 1
                            border.color: step.on ? Theme.accent : Theme.line
                            Row {
                                id: node
                                anchors.centerIn: parent
                                spacing: 7
                                Text {
                                    text: (step.index + 1) + "."
                                    color: Theme.muted
                                    font.pixelSize: 11
                                    font.weight: Font.Bold
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: step.modelData.glyph
                                    color: step.on ? Theme.accentInk : Theme.muted
                                    font.pixelSize: 13
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: i18n.t(step.modelData.label)
                                    color: step.on ? Theme.accentInk : Theme.muted
                                    font.pixelSize: 13
                                    font.weight: step.on ? Font.DemiBold : Font.Normal
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                            TapHandler {
                                onTapped: backend.distSetAction(step.modelData.key, !step.on)
                            }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                        }
                        Text {
                            visible: step.index < DistActions.chain.length - 1
                            text: "→"
                            color: Theme.muted
                            font.pixelSize: 13
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
            }
        }

        // -- firmware cache: only when the firmware step is in the chain --------------
        Card {
            Layout.fillWidth: true
            visible: root.dist.editable && !!root.actions.firmware
            title: i18n.t("dist_fw_title")

            RowLayout {
                Layout.fillWidth: true
                Chip {
                    text: i18n.t("offline_ready")
                    fg: Theme.blue
                    bg: Theme.blueSoft
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    ghost: true
                    text: i18n.t("update_caches")
                    enabled: backend.busy === ""
                    onClicked: backend.updateCaches()
                }
            }
            Text {
                Layout.fillWidth: true
                visible: (backend.cacheStatus.entries || []).length === 0
                text: i18n.t("dist_fw_empty")
                color: Theme.muted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
            Repeater {
                model: backend.cacheStatus.entries || []
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 8
                    Text {
                        text: (modelData.model || "").toUpperCase()
                              + " · Epsilon " + modelData.version
                        color: Theme.ink
                        font.pixelSize: 13
                    }
                    Chip { text: modelData.channel || "stable"; fg: Theme.muted; bg: Theme.panel }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: Math.round((modelData.size || 0) / 1024) + " Kio"
                        color: Theme.muted
                        font.pixelSize: 12
                        font.family: Theme.mono
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                text: i18n.t("dist_fw_ttl", { n: backend.cacheStatus.expires_in_days || 30 })
                color: Theme.muted
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
        }

        DistSetCard {
            Layout.fillWidth: true
            visible: root.dist.editable && !!root.actions.apps
            title: i18n.t("roster_dist_apps")
            kind: "apps"
            available: root.dist.availableApps
            chosen: root.dist.apps
            emptyText: i18n.t("dist_no_apps")
        }
        DistSetCard {
            Layout.fillWidth: true
            visible: root.dist.editable && !!root.actions.scripts
            title: i18n.t("roster_dist_scripts")
            kind: "scripts"
            available: root.dist.availableScripts
            chosen: root.dist.scripts
            emptyText: i18n.t("dist_no_scripts")
        }

        Text {
            Layout.fillWidth: true
            visible: root.dist.editable
            text: "⚠  " + i18n.t("dist_foot")
            color: Theme.accentInk
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
    }
}
