import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

/* Classroom fleet table. Keyboard and range-selection are the desktop additions; the
   checkboxes, the name filter and the bulk bar are what the web view already had. */
Item {
    id: root
    property var selection: ({})
    property int lastClicked: -1
    property int selCount: 0   // selected AND visible: the bulk bar counts what the eye counts

    // F2 used to call a method on `rows.currentItem`: untyped, and null as soon as the current
    // row leaves the reuse pool. The row that owns the index answers instead.
    signal renameRow(int index)

    function selectedKeys() {
        return Object.keys(root.selection).filter((k) => root.selection[k])
    }
    function countSel() {
        let n = 0
        for (let i = 0; i < backend.rosterRows.rowCount(); i++)
            if (root.selection[backend.rosterRows.get(i).key]) n++
        root.selCount = n
    }
    function setSel(key, on) {
        let s = root.selection
        s[key] = on
        root.selection = s
        root.countSel()
    }
    function clearSel() { root.selection = ({}); root.selCount = 0 }
    function selectAll(on) {
        // Visible rows only, the rest of the selection untouched — a filtered-out calculator
        // stays selected, as in the web table.
        let s = root.selection
        for (let i = 0; i < backend.rosterRows.rowCount(); i++)
            s[backend.rosterRows.get(i).key] = on
        root.selection = s
        root.countSel()
    }
    Connections {
        target: backend
        // A refresh is not a reason to forget the selection — typing in the filter causes one on
        // every keystroke. Only calculators that left the register are dropped.
        function onRosterChanged() {
            let s = {}
            for (const k of backend.rosterKeys) if (root.selection[k]) s[k] = true
            root.selection = s
            root.countSel()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // -- bulk bar: only while something is selected -----------------------------
        Rectangle {
            Layout.fillWidth: true
            visible: root.selCount > 0
            implicitHeight: 46
            color: Theme.accentSoft
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 10
                Text {
                    text: i18n.t("roster_bulk_selected", { n: root.selCount })
                    color: Theme.accentInk
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Item { Layout.fillWidth: true }
                AppComboBox {
                    id: moveTo
                    Layout.preferredWidth: 200
                    font.pixelSize: 13
                    Accessible.name: i18n.t("roster_move_to")
                    model: [i18n.t("roster_move_to")]
                        .concat(backend.classNames)
                        .concat([i18n.t("roster_unfiled")])
                    onActivated: (i) => {
                        if (i === 0) return
                        const cls = (i === count - 1) ? "" : backend.classNames[i - 1]
                        backend.rosterMove(root.selectedKeys(), cls)
                        currentIndex = 0
                    }
                }
                AppButton {
                    ghost: true
                    text: i18n.t("roster_delete")
                    onClicked: backend.rosterDelete(root.selectedKeys())
                }
            }
        }

        // -- header -----------------------------------------------------------------
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 44
            color: Theme.card
            Rectangle { width: parent.width; height: 1; y: parent.height - 1; color: Theme.line }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 0
                Item {
                    Layout.preferredWidth: 34
                    Layout.fillHeight: true
                    AppCheckBox {
                        anchors.centerIn: parent
                        checked: root.selCount > 0
                                 && root.selCount === backend.rosterRows.rowCount()
                        onToggled: root.selectAll(checked)
                        Accessible.name: i18n.t("roster_select_all")
                        ToolTip.visible: hovered
                        ToolTip.text: i18n.t("roster_select_all")
                    }
                }
                HeaderCell { Layout.preferredWidth: 54; text: i18n.t("roster_col_type") }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HeaderCell { text: i18n.t("roster_col_name") }
                    AppTextField {
                        id: filterField
                        Layout.preferredWidth: 170
                        compact: true
                        placeholderText: i18n.t("roster_filter")
                        Accessible.name: i18n.t("roster_filter_name")
                        onTextEdited: backend.setFilter(text)
                        // Typing breaks a plain `text:` binding for good, and the field then
                        // ignores a filter cleared from the backend. Reassert it whenever the
                        // field is not the one doing the writing.
                        // RestoreNone: taking focus must not hand the field back an older value.
                        Binding on text {
                            value: backend.parcFilter
                            when: !filterField.activeFocus
                            restoreMode: Binding.RestoreNone
                        }
                    }
                    Item { Layout.fillWidth: true }
                }
                HeaderCell { Layout.preferredWidth: 190; text: i18n.t("roster_known_fw") }
                HeaderCell { Layout.preferredWidth: 150; text: i18n.t("roster_col_dist") }
                HeaderCell { Layout.preferredWidth: 150; text: i18n.t("roster_col_lastscan") }
            }
        }

        // -- rows -------------------------------------------------------------------
        ListView {
            id: rows
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: backend.rosterRows
            focus: true
            ScrollBar.vertical: AppScrollBar {}

            Text {
                anchors.centerIn: parent
                visible: rows.count === 0
                text: backend.parcFilter !== "" ? i18n.t("no_match") : i18n.t("roster_empty")
                color: Theme.muted
                font.pixelSize: 13
            }

            Keys.onPressed: (e) => {
                if (e.key === Qt.Key_Delete || e.key === Qt.Key_Backspace) {
                    const keys = root.selectedKeys()
                    if (keys.length) backend.rosterDelete(keys)
                    e.accepted = true
                } else if (e.key === Qt.Key_A
                           && (e.modifiers & (Qt.ControlModifier | Qt.MetaModifier))) {
                    root.selectAll(true)
                    e.accepted = true
                } else if (e.key === Qt.Key_F2 && rows.currentIndex >= 0) {
                    root.renameRow(rows.currentIndex)
                    e.accepted = true
                } else if (e.key === Qt.Key_Escape) {
                    root.clearSel()
                    e.accepted = true
                }
            }

            delegate: Rectangle {
                id: row
                required property int index
                required property string key
                required property string displayName
                required property string family
                required property string knownFirmware
                required property bool upToDate
                required property string lastScanKey
                required property int lastScanN
                required property var lastDist

                width: rows.width
                height: 52
                opacity: dragHandler.active ? 0.5 : 1
                color: root.selection[row.key] ? Theme.accentSoft
                     : rowHover.hovered ? Theme.panel : "transparent"
                function startRename() { nameEdit.visible = true; nameEdit.forceActiveFocus() }
                Connections {
                    target: root
                    function onRenameRow(i) { if (i === row.index) row.startRename() }
                }

                Rectangle { width: parent.width; height: 1; y: parent.height - 1; color: Theme.line }
                HoverHandler { id: rowHover }

                // Drag a row onto a class in the rail. If the row is part of the current
                // selection, the whole selection travels with it.
                Drag.active: dragHandler.active
                Drag.dragType: Drag.Automatic
                Drag.supportedActions: Qt.MoveAction
                Drag.mimeData: {
                    "nwupdater/roster-keys": (root.selection[row.key]
                        ? root.selectedKeys() : [row.key]).join("\n")
                }
                DragHandler {
                    id: dragHandler
                    target: null
                    onActiveChanged: if (active && !root.selection[row.key]) {
                        root.clearSel()
                        root.setSel(row.key, true)
                    }
                }

                TapHandler {
                    acceptedModifiers: Qt.NoModifier
                    onTapped: {
                        rows.currentIndex = row.index
                        root.clearSel()
                        root.setSel(row.key, true)
                        root.lastClicked = row.index
                        rows.forceActiveFocus()
                    }
                    onDoubleTapped: row.startRename()
                }
                TapHandler {
                    acceptedModifiers: Qt.ShiftModifier
                    onTapped: {
                        const anchor = root.lastClicked < 0 ? row.index : root.lastClicked
                        const a = Math.min(anchor, row.index), b = Math.max(anchor, row.index)
                        let s = root.selection
                        for (let i = a; i <= b; i++) s[backend.rosterRows.get(i).key] = true
                        root.selection = s
                        root.countSel()   // visible-only, like every other selection path
                        rows.currentIndex = row.index
                    }
                }
                TapHandler {
                    acceptedModifiers: Qt.ControlModifier | Qt.MetaModifier
                    onTapped: {
                        root.setSel(row.key, !root.selection[row.key])
                        root.lastClicked = row.index
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    spacing: 0

                    Item {
                        Layout.preferredWidth: 34
                        Layout.fillHeight: true
                        AppCheckBox {
                            anchors.centerIn: parent
                            checked: !!root.selection[row.key]
                            onToggled: root.setSel(row.key, checked)
                        }
                    }
                    Item {
                        Layout.preferredWidth: 54
                        Layout.fillHeight: true
                        Image {
                            anchors.centerIn: parent
                            source: "../assets/calc-"
                                    + (row.family === "scientifique" ? "scientific" : "graphing")
                                    + "-icon.svg"
                            sourceSize.width: 30
                            fillMode: Image.PreserveAspectFit
                        }
                    }
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: !nameEdit.visible
                            width: parent.width - 8
                            text: row.displayName
                            color: Theme.ink
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        AppTextField {
                            id: nameEdit
                            anchors.verticalCenter: parent.verticalCenter
                            visible: false
                            width: parent.width - 12
                            compact: true
                            text: row.displayName
                            onAccepted: { backend.rosterRename(row.key, text); visible = false }
                            Keys.onEscapePressed: { text = row.displayName; visible = false }
                            onActiveFocusChanged: if (!activeFocus) visible = false
                        }
                    }
                    RowLayout {
                        Layout.preferredWidth: 190
                        spacing: 8
                        Text {
                            text: row.knownFirmware === "—"
                                  ? "—" : "Epsilon " + row.knownFirmware
                            color: Theme.ink
                            font.pixelSize: 13
                        }
                        Chip {
                            visible: row.knownFirmware !== "—"
                            text: row.upToDate ? i18n.t("roster_uptodate") : i18n.t("roster_needs")
                            fg: row.upToDate ? Theme.ok : Theme.accentInk
                            bg: row.upToDate ? Theme.okSoft : Theme.accentSoft
                        }
                        Item { Layout.fillWidth: true }
                    }
                    Item {
                        Layout.preferredWidth: 150
                        Layout.fillHeight: true
                        DistOutcomes {
                            anchors.verticalCenter: parent.verticalCenter
                            outcomes: row.lastDist
                        }
                    }
                    RowLayout {
                        Layout.preferredWidth: 150
                        spacing: 6
                        Text {
                            text: i18n.t(row.lastScanKey, { n: row.lastScanN })
                            color: Theme.muted
                            font.pixelSize: 13
                        }
                        Item { Layout.fillWidth: true }
                        IconGhostButton {   // hover trash, like the web row
                            visible: rowHover.hovered
                            glyph: "🗑"
                            tip: i18n.t("roster_delete")
                            onTriggered: backend.rosterDelete([row.key])
                        }
                    }
                }
            }
        }
    }
}
