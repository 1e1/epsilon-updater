import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtCore
import QtQuick.Window

/* The real OS window — no simulated chrome. What the web UI drew in HTML (a centred 1140px
   frame, a fake title bar, a Quit button, a fixed-position toast) the desktop provides.

   This file is structure only: the menu bar, the tab strip, the confirmation bar, the status
   line and the two empty states are each their own component. What stays here is the window,
   which tab is current, and which pane answers to it. */
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
    property string currentTab: "system"
    property string classDeletePending: ""

    // Workshops follow the hardware: the apps tab needs an external QSPI region, the scripts tab
    // needs Python storage. Both are absent on an N0200.
    readonly property var visibleTabs: {
        if (win.classroom)
            return [{ k: "parc", l: i18n.t("roster_tab_calc"), n: (backend.roster.total || 0) },
                    { k: "dist", l: i18n.t("roster_tab_dist"), n: -1 }]
        let list = [{ k: "system", l: i18n.t("tab_system"), n: -1 }]
        if (backend.appsPlan.enabled)
            list.push({ k: "apps", l: i18n.t("tab_apps"), n: (backend.appsPlan.deviceCount || 0) })
        if (backend.scriptsPlan.enabled)
            list.push({ k: "scripts", l: i18n.t("tab_scripts"),
                        n: (backend.scriptsPlan.deviceCount || 0) })
        return list
    }
    readonly property var tabOrder: win.visibleTabs.map((t) => t.k)
    onTabOrderChanged: if (win.tabOrder.indexOf(win.currentTab) < 0 && win.tabOrder.length)
                           win.currentTab = win.tabOrder[0]
    onClassroomChanged: {
        win.currentTab = win.classroom ? "parc" : "system"
        win.classDeletePending = ""
    }

    function currentKind() { return win.currentTab === "scripts" ? "scripts" : "apps" }
    function currentPlan() {
        return win.currentTab === "scripts" ? backend.scriptsPlan : backend.appsPlan
    }
    /* Which component answers for a tab. Reading `backend.connected` here is what makes the
       binding re-evaluate when the cable moves — QML tracks the property reads a function
       performs, not just the ones written inline. */
    function paneFor(key) {
        if (key === "parc")
            return rosterPaneC
        if (key === "dist")
            return distributionPaneC
        if (!backend.connected)
            return noDevicePaneC
        if (key === "apps")
            return appsWorkshopC
        if (key === "scripts")
            return scriptsWorkshopC
        return systemPaneC
    }

    // Geometry and preferences survive a restart (Qt.labs.settings equivalent in QtCore).
    Settings {
        id: prefs
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
        i18n.lang = prefs.lang
        Theme.dark = prefs.theme === "dark"
            || (prefs.theme === "auto" && win.palette.window.hsvValue < 0.5)
    }

    AppMenuBar {
        connected: backend.connected
        canUndo: win.currentPlan().canUndo === true
        canReset: win.currentPlan().dirty === true
        railCollapsed: split.collapsed
        dark: Theme.dark
        mode: backend.mode
        lang: i18n.lang
        onRescanRequested: backend.rescan()
        onDetachRequested: backend.detach()
        onUndoRequested: backend.stageUndo(win.currentKind())
        onResetRequested: backend.stageReset(win.currentKind())
        onModePicked: (m) => backend.setMode(m)
        onDarkPicked: (on) => { Theme.dark = on; prefs.theme = on ? "dark" : "light" }
        onRailPicked: (collapsed) => split.collapsed = collapsed
        onLangPicked: (l) => { i18n.lang = l; prefs.lang = l }
    }

    // -- body: resizable, collapsible rail + panes ----------------------------------------
    SplitView {
        id: split
        anchors.fill: parent
        orientation: Qt.Horizontal
        property real railWidth: 280
        property bool collapsed: false

        handle: Rectangle {
            implicitWidth: 1
            color: SplitHandle.pressed || SplitHandle.hovered ? Theme.accent : Theme.line
            Behavior on color { ColorAnimation { duration: 120 } }
        }

        Rectangle {
            id: rail
            SplitView.preferredWidth: split.collapsed ? 0 : split.railWidth
            SplitView.minimumWidth: split.collapsed ? 0 : 232
            SplitView.maximumWidth: 360
            visible: !split.collapsed
            color: Theme.panel
            onWidthChanged: if (!split.collapsed && width > 0) split.railWidth = width

            Loader {
                anchors.fill: parent
                anchors.margins: 16
                sourceComponent: win.classroom ? classesRailC
                               : (backend.connected ? devicePanelC : noDeviceRailC)
            }
        }

        ColumnLayout {
            SplitView.fillWidth: true
            spacing: 0

            TabStrip {
                Layout.fillWidth: true
                tabs: win.visibleTabs
                current: win.currentTab
                classroom: win.classroom
                canDeleteClass: backend.parcClass !== backend.classAll
                                && backend.parcClass !== backend.classUnfiled
                onPicked: (k) => win.currentTab = k
                onDeleteClassRequested: win.classDeletePending = backend.parcClass
                onBatchRequested: win.openBatch()
            }

            ClassDeleteBar {
                Layout.fillWidth: true
                visible: win.classDeletePending !== ""
                className: win.classDeletePending
                population: backend.selectedClassCount
                onCancelled: win.classDeletePending = ""
                onChose: (mode) => {
                    backend.classDelete(win.classDeletePending, mode)
                    win.classDeletePending = ""
                }
            }

            // Panes: a StackLayout of live views — each keeps its scroll and focus.
            StackLayout {
                id: panes
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: Math.max(0, win.tabOrder.indexOf(win.currentTab))

                Repeater {
                    model: win.tabOrder
                    delegate: LazyPane {
                        required property string modelData
                        required property int index
                        shown: panes.currentIndex === index
                        sourceComponent: win.paneFor(modelData)
                    }
                }
            }

            StatusBar { Layout.fillWidth: true }
        }
    }

    // -- batch: a real second window, not an overlay ---------------------------------------
    // Instantiated on first arming, not at startup: an idle second Window costs memory and a
    // scene graph for a mode most sessions never enter.
    property Window batchWindow: null
    function openBatch() {
        if (!backend.armBatch())
            return
        if (win.batchWindow === null)
            win.batchWindow = batchWindowC.createObject(win)
        win.batchWindow.show()
        win.batchWindow.raise()
    }
    Component { id: batchWindowC; BatchWindow {} }

    // -- components ------------------------------------------------------------------------
    Component { id: rosterPaneC; RosterPane {} }
    Component { id: distributionPaneC; DistributionPane {} }
    Component { id: classesRailC; ClassesRail {} }
    Component { id: systemPaneC; SystemPane {} }
    Component { id: noDeviceRailC; NoDeviceRail {} }
    Component { id: noDevicePaneC; NoDevicePane {} }
    Component {
        id: devicePanelC
        DevicePanel { identity: backend.identity; deviceName: backend.deviceName }
    }
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
}
