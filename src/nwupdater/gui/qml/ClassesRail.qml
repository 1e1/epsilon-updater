import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

/* Classroom rail: the class buckets. Each one is a drop target, so filing calculators is a
   drag from the table — the gesture the web UI had. */
ColumnLayout {
    id: root
    spacing: 6

    Text {
        Layout.topMargin: 4
        text: i18n.t("classes")
        color: Theme.muted
        font.pixelSize: 11
        font.weight: Font.Bold
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.8
    }

    ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 2
        model: backend.classes
        ScrollBar.vertical: AppScrollBar {}

        delegate: Rectangle {
            id: bucket
            required property string classId
            required property string label
            required property int count
            required property string icon

            width: list.width
            height: 36
            radius: 9
            readonly property bool active: backend.parcClass === bucket.classId
            color: bucket.active ? Theme.accentSoft : (hov.hovered ? Theme.card : "transparent")

            readonly property bool renameable: bucket.classId !== "__all__"
                                            && bucket.classId !== "__unfiled__"

            HoverHandler { id: hov; cursorShape: Qt.PointingHandCursor }
            TapHandler {
                onTapped: backend.selectClass(bucket.classId)
                onDoubleTapped: if (bucket.renameable) {   // inline rename, as in the web rail
                    nameEdit.text = bucket.label
                    nameEdit.visible = true
                    nameEdit.forceActiveFocus()
                    nameEdit.selectAll()
                }
            }
            ToolTip.visible: hov.hovered && bucket.renameable && !nameEdit.visible
            ToolTip.text: i18n.t("roster_rename_hint")
            ToolTip.delay: 700

            AppTextField {
                id: nameEdit
                anchors.fill: parent
                anchors.margins: 3
                visible: false
                compact: true
                onAccepted: {
                    if (text.trim() && text.trim() !== bucket.label)
                        backend.classRename(bucket.label, text.trim())
                    visible = false
                }
                Keys.onEscapePressed: visible = false
                onActiveFocusChanged: if (!activeFocus) visible = false
            }

            DropArea {
                id: classDrop
                anchors.fill: parent
                enabled: bucket.classId !== "__all__"   // "All" is a view, not a bucket
                keys: ["nwupdater/roster-keys"]
                onDropped: (ev) => {
                    const keys = ev.getDataAsString("nwupdater/roster-keys")
                                   .split("\n").filter((k) => k !== "")
                    if (keys.length)
                        backend.rosterMove(keys, bucket.classId === "__unfiled__"
                                                 ? "" : bucket.classId)
                    ev.acceptProposedAction()
                }
            }
            Rectangle {
                anchors.fill: parent
                visible: classDrop.containsDrag
                radius: 9
                color: "transparent"
                border.width: 2
                border.color: Theme.accent
            }

            RowLayout {
                visible: !nameEdit.visible
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 9

                Text {
                    text: bucket.icon === "stack" ? "▤" : bucket.icon === "inbox" ? "▽" : "▸"
                    color: bucket.active ? Theme.accentInk : Theme.muted
                    font.pixelSize: 12
                }
                Text {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 0
                    text: bucket.classId === "__all__" ? i18n.t("roster_all")
                        : bucket.classId === "__unfiled__" ? i18n.t("roster_unfiled")
                        : bucket.label
                    color: bucket.active ? Theme.accentInk : Theme.ink
                    font.pixelSize: 13
                    font.weight: bucket.active ? Font.DemiBold : Font.Normal
                    elide: Text.ElideRight
                }
                Text {
                    text: bucket.count
                    color: Theme.muted
                    font.pixelSize: 12
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        AppTextField {
            id: newClass
            Layout.fillWidth: true
            Layout.preferredWidth: 0
            placeholderText: i18n.t("roster_new_class")
            onAccepted: if (text.trim()) { backend.classCreate(text.trim()); text = "" }
        }
        AppButton {
            text: "+"
            ghost: true
            implicitWidth: 34
            onClicked: if (newClass.text.trim()) {
                backend.classCreate(newClass.text.trim())
                newClass.text = ""
            }
        }
    }
}
