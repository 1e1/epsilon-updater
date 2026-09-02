import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtCore
import Qt.labs.platform as Platform
import QtQuick.Window

/* The real OS window — no simulated chrome. What the web UI drew in HTML (a centred 1140px
   frame, a fake title bar, a Quit button, a fixed-position toast) the desktop provides. */
ApplicationWindow {
    id: win
    width: 1180
    height: 780
    minimumWidth: 900
    minimumHeight: 600
    visible: true
    title: "nwupdater"
    color: Theme.bg

    readonly property bool classroom: backend.mode === "classroom"
    onClassroomChanged: {
        tabs.currentTab = classroom ? "parc" : "system"
        classDeletePending = ""
    }
    property string classDeletePending: ""

    // Geometry survives a restart (Qt.labs.settings equivalent in QtCore).
    Settings {
        id: geometry
        category: "window"
        property alias x: win.x
        property alias y: win.y
        property alias width: win.width
        property alias height: win.height
        property alias railWidth: split.railWidth
        property string lang: "fr"
        property string theme: "auto"
    }
    Component.onCompleted: {
        i18n.lang = geometry.lang
        Theme.dark = geometry.theme === "dark"
            || (geometry.theme === "auto" && win.palette.window.hsvValue < 0.5)
    }

    // -- native menu bar: doubles what is on screen, never replaces it ------------------
    Platform.MenuBar {
        Platform.Menu {
            title: i18n.t("menu_file")
            Platform.MenuItem {
                text: i18n.t("rescan")
                shortcut: "Ctrl+R"
                onTriggered: backend.rescan()
            }
            Platform.MenuItem {
                text: i18n.t("dev_menu")
                enabled: backend.connected
                onTriggered: backend.detach()
            }
            Platform.MenuSeparator {}
            Platform.MenuItem {
                text: i18n.t("quit")
                role: Platform.MenuItem.QuitRole
                shortcut: StandardKey.Quit
                onTriggered: Qt.quit()
            }
        }
        Platform.Menu {
            title: i18n.t("menu_edit")
            Platform.MenuItem {
                text: i18n.t("undo")
                shortcut: StandardKey.Undo
                enabled: win.currentPlan().canUndo === true
                onTriggered: backend.stageUndo(win.currentKind())
            }
            Platform.MenuItem {
                text: i18n.t("reset")
                enabled: win.currentPlan().dirty === true
                onTriggered: backend.stageReset(win.currentKind())
            }
        }
        Platform.Menu {
            title: i18n.t("menu_mode")
            Platform.MenuItem {
                text: i18n.t("mode_individual")
                checkable: true
                checked: backend.mode === "individual"
                shortcut: "Ctrl+1"
                onTriggered: backend.setMode("individual")
            }
            Platform.MenuItem {
                text: i18n.t("mode_classroom")
                checkable: true
                checked: backend.mode === "classroom"
                shortcut: "Ctrl+2"
                onTriggered: backend.setMode("classroom")
            }
        }
        Platform.Menu {
            title: i18n.t("menu_view")
            Platform.MenuItem {
                text: i18n.t("theme_dark")
                checkable: true
                checked: Theme.dark
                onTriggered: { Theme.dark = checked; geometry.theme = checked ? "dark" : "light" }
            }
            Platform.MenuItem {
                text: i18n.t("collapse_rail")
                checkable: true
                checked: split.collapsed
                shortcut: "Ctrl+B"
                onTriggered: split.collapsed = checked
            }
            Platform.MenuSeparator {}
            Platform.MenuItem {
                text: "Français"
                checkable: true
                checked: i18n.lang === "fr"
                onTriggered: { i18n.lang = "fr"; geometry.lang = "fr" }
            }
            Platform.MenuItem {
                text: "English"
                checkable: true
                checked: i18n.lang === "en"
                onTriggered: { i18n.lang = "en"; geometry.lang = "en" }
            }
        }
    }

    function selectTab(name) { tabs.currentTab = name }
    function currentKind() { return tabs.currentTab === "scripts" ? "scripts" : "apps" }
    function currentPlan() {
        return tabs.currentTab === "scripts" ? backend.scriptsPlan : backend.appsPlan
    }

    // -- toolbar: mode + language only; everything else moved to the menu or the panes ----
    // -- body: resizable, collapsible rail + panes ----------------------------------------
    SplitView {
        id: split
        anchors.fill: parent
        orientation: Qt.Horizontal
        property real railWidth: 250
        property bool collapsed: false

        handle: Rectangle {
            implicitWidth: 1
            color: SplitHandle.pressed || SplitHandle.hovered ? Theme.accent : Theme.line
            Behavior on color { ColorAnimation { duration: 120 } }
        }

        Rectangle {
            id: rail
            SplitView.preferredWidth: split.collapsed ? 0 : split.railWidth
            SplitView.minimumWidth: split.collapsed ? 0 : 190
            SplitView.maximumWidth: 360
            visible: !split.collapsed
            color: Theme.panel
            onWidthChanged: if (!split.collapsed && width > 0) split.railWidth = width

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10

                Loader {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: win.classroom ? classesRailC
                                   : (backend.connected ? devicePanelC : noDeviceC)
                }
            }
        }

        ColumnLayout {
            SplitView.fillWidth: true
            spacing: 0

            // Tab strip — navigation only. The batch action lives in the pane's own action bar.
            Rectangle {
                Layout.fillWidth: true
                height: 42
                color: Theme.card
                Rectangle { width: parent.width; height: 1; y: parent.height - 1; color: Theme.line }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    spacing: 4
                    Repeater {
                        model: tabs.visibleTabs
                        delegate: Item {
                            required property var modelData
                            readonly property bool active: tabs.currentTab === modelData.k
                            implicitWidth: tabRow.implicitWidth + 20
                            implicitHeight: 42
                            Row {
                                id: tabRow
                                anchors.centerIn: parent
                                spacing: 7
                                Text {
                                    text: modelData.l
                                    color: parent.parent.active ? Theme.ink : Theme.muted
                                    font.pixelSize: 14
                                    font.weight: parent.parent.active ? Font.DemiBold : Font.Normal
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Chip {
                                    visible: modelData.n >= 0
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.n
                                    fg: Theme.muted
                                    bg: Theme.panel
                                }
                            }
                            Rectangle {
                                visible: parent.active
                                width: parent.width - 12
                                height: 2
                                x: 6
                                y: parent.height - 2
                                color: Theme.accent
                            }
                            TapHandler { onTapped: tabs.currentTab = modelData.k }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    AppButton {
                        visible: win.classroom
                        ghost: true
                        text: "🗑"
                        implicitWidth: 38
                        enabled: backend.parcClass !== "__all__"
                                 && backend.parcClass !== "__unfiled__"
                        onClicked: win.classDeletePending = backend.parcClass
                    }
                    AppButton {
                        visible: win.classroom
                        text: "▶  " + i18n.t("batch_mode")
                        onClicked: win.openBatch()
                    }
                }
            }

            // Deleting a class is destructive in two different ways, so it asks which one.
            Rectangle {
                Layout.fillWidth: true
                visible: win.classDeletePending !== ""
                implicitHeight: 48
                color: Theme.accentSoft
                Rectangle { width: parent.width; height: 1; y: parent.height - 1; color: Theme.line }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    spacing: 10
                    Text { text: "⚠"; color: Theme.accentInk; font.pixelSize: 15 }
                    Text {
                        Layout.fillWidth: true
                        text: i18n.t("roster_delete_class_confirm",
                                     { c: win.classDeletePending,
                                       n: backend.selectedClassCount })
                        color: Theme.accentInk
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }
                    AppButton {
                        ghost: true
                        text: i18n.t("roster_cancel")
                        onClicked: win.classDeletePending = ""
                    }
                    AppButton {
                        text: i18n.t("roster_delete_class_move")
                        onClicked: {
                            backend.classDelete(win.classDeletePending, "move")
                            win.classDeletePending = ""
                        }
                    }
                    AppButton {
                        danger: true
                        text: i18n.t("roster_delete_class_purge",
                                     { n: backend.selectedClassCount })
                        onClicked: {
                            backend.classDelete(win.classDeletePending, "purge")
                            win.classDeletePending = ""
                        }
                    }
                }
            }

            // Panes: a StackLayout of live views — each keeps its scroll and focus.
            StackLayout {
                id: tabs
                property string currentTab: "system"

                // Workshops follow the hardware: the apps tab needs an external QSPI region, the
                // scripts tab needs Python storage. Both are absent on an N0200.
                readonly property var visibleTabs: {
                    if (win.classroom)
                        return [{ k: "parc", l: i18n.t("roster_tab_calc"),
                                  n: (backend.roster.total || 0) },
                                { k: "dist", l: i18n.t("roster_tab_dist"), n: -1 }]
                    let list = [{ k: "system", l: i18n.t("tab_system"), n: -1 }]
                    if (backend.appsPlan.enabled)
                        list.push({ k: "apps", l: i18n.t("tab_apps"),
                                    n: (backend.appsPlan.deviceCount || 0) })
                    if (backend.scriptsPlan.enabled)
                        list.push({ k: "scripts", l: i18n.t("tab_scripts"),
                                    n: (backend.scriptsPlan.deviceCount || 0) })
                    return list
                }
                readonly property var order: visibleTabs.map((t) => t.k)
                onOrderChanged: if (order.indexOf(currentTab) < 0 && order.length)
                                    currentTab = order[0]

                visible: !win.classroom
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: Math.max(0, order.indexOf(currentTab))

                Repeater {
                    model: win.classroom ? [] : tabs.order
                    delegate: LazyPane {
                        required property string modelData
                        required property int index
                        shown: tabs.currentIndex === index
                        sourceComponent: !backend.connected ? noDeviceMainC
                                       : modelData === "system" ? systemPaneC
                                       : modelData === "apps" ? appsWorkshopC
                                       : scriptsWorkshopC
                    }
                }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: win.classroom
                currentIndex: tabs.currentTab === "dist" ? 1 : 0
                LazyPane {
                    shown: win.classroom && tabs.currentTab === "parc"
                    sourceComponent: rosterPaneC
                }
                LazyPane {
                    shown: win.classroom && tabs.currentTab === "dist"
                    sourceComponent: distributionPaneC
                }
            }

            // Status bar — kept (a notification can be silenced by the OS; this cannot).
            Rectangle {
                Layout.fillWidth: true
                height: 28
                color: Theme.chrome
                Rectangle { width: parent.width; height: 1; color: Theme.line }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    spacing: 10
                    Rectangle {
                        width: 7; height: 7; radius: 4
                        color: backend.connected ? Theme.ok : Theme.muted
                    }
                    Text {
                        text: win.classroom ? i18n.t("mode_classroom") : i18n.t("mode_individual")
                        color: Theme.accentInk
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                    Rectangle {
                        visible: statusText.text !== ""
                        width: 1; height: 12
                        color: Theme.line
                    }
                    QtObject {
                        id: statusText
                        property string text: ""
                        property bool error: false
                    }
                    Text {
                        visible: statusText.text !== ""
                        text: statusText.text
                        color: statusText.error ? Theme.err : Theme.muted
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: "🔒  " + i18n.t("disc")
                        color: Theme.muted
                        font.pixelSize: 11
                    }
                }
                Connections {
                    target: backend
                    function onToast(message, isError) {
                        statusText.text = message
                        statusText.error = isError
                        statusReset.restart()
                    }
                }
                Timer {
                    id: statusReset
                    interval: 6000
                    onTriggered: { statusText.text = ""; statusText.error = false }
                }
            }
        }
    }

    // -- batch: a real second window, not an overlay ---------------------------------------
    // Instantiated on first arming, not at startup: an idle second Window costs memory and a
    // scene graph for a mode most sessions never enter.
    property Window batchWindow: null
    function openBatch() {
        if (!backend.armBatch())
            return
        if (batchWindow === null)
            batchWindow = batchWindowC.createObject(win)
        batchWindow.show()
        batchWindow.raise()
    }
    Component { id: batchWindowC; BatchWindow {} }

    // -- components ------------------------------------------------------------------------
    Component { id: rosterPaneC; RosterPane {} }
    Component { id: distributionPaneC; DistributionPane {} }
    Component { id: devicePanelC; DevicePanel { identity: backend.identity; deviceName: backend.deviceName } }
    Component { id: classesRailC; ClassesRail {} }
    Component { id: systemPaneC; SystemPane {} }
    Component {
        id: appsWorkshopC
        WorkshopPane {
            kind: "apps"
            plan: backend.appsPlan
            deviceModel: backend.appsDeviceModel
            availModel: backend.appsAvailModel
        }
    }
    Component {
        id: scriptsWorkshopC
        WorkshopPane {
            kind: "scripts"
            plan: backend.scriptsPlan
            deviceModel: backend.scriptsDeviceModel
            availModel: backend.scriptsAvailModel
        }
    }
    Component {
        id: noDeviceC
        ColumnLayout {
            spacing: 10
            Item { Layout.fillHeight: true }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "🔌"; font.pixelSize: 30
            }
            Text {
                Layout.fillWidth: true
                text: i18n.t("nodev_title")
                color: Theme.muted
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }
            AppButton { Layout.fillWidth: true; text: i18n.t("rescan"); onClicked: backend.rescan() }
            ComboBox {
                id: demoPick
                Layout.fillWidth: true
                model: backend.demoModels
                textRole: "name"
                font.pixelSize: 12
            }
            AppButton {
                Layout.fillWidth: true
                ghost: true
                text: i18n.t("demo_btn")
                onClicked: backend.exploreDemo(backend.demoModels[demoPick.currentIndex].name)
            }
            Item { Layout.fillHeight: true }
        }
    }
    Component {
        id: noDeviceMainC
        Item {
            Column {
                anchors.centerIn: parent
                spacing: 8
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "🔌"; font.pixelSize: 34; opacity: 0.7
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: i18n.t("nodev_title")
                    color: Theme.muted
                    font.pixelSize: 13
                }
            }
        }
    }
}
