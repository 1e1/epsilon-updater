import QtQuick
import Qt.labs.platform as Platform

/* The native menu bar. It doubles what is on screen, never replaces it (docs §3): every action
   here also has a visible control, so a build that ends up without a menu bar is degraded, not
   crippled.

   Nothing is read from the window directly — the state it needs arrives as properties and it
   reports back with signals, so the menu can be read without holding the whole scene in your
   head. */
Platform.MenuBar {
    id: root
    property bool connected: false
    property bool canUndo: false
    property bool canReset: false
    property bool railCollapsed: false
    property bool dark: false
    property string mode: "individual"
    property string lang: "fr"

    signal rescanRequested()
    signal detachRequested()
    signal undoRequested()
    signal resetRequested()
    signal modePicked(string mode)
    signal darkPicked(bool on)
    signal railPicked(bool collapsed)
    signal langPicked(string lang)

    Platform.Menu {
        title: i18n.t("menu_file")
        Platform.MenuItem {
            text: i18n.t("rescan")
            shortcut: "Ctrl+R"
            onTriggered: root.rescanRequested()
        }
        Platform.MenuItem {
            text: i18n.t("dev_menu")
            enabled: root.connected
            onTriggered: root.detachRequested()
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
            enabled: root.canUndo
            onTriggered: root.undoRequested()
        }
        Platform.MenuItem {
            text: i18n.t("reset")
            enabled: root.canReset
            onTriggered: root.resetRequested()
        }
    }
    Platform.Menu {
        title: i18n.t("menu_mode")
        Platform.MenuItem {
            text: i18n.t("mode_individual")
            checkable: true
            checked: root.mode === "individual"
            shortcut: "Ctrl+1"
            onTriggered: root.modePicked("individual")
        }
        Platform.MenuItem {
            text: i18n.t("mode_classroom")
            checkable: true
            checked: root.mode === "classroom"
            shortcut: "Ctrl+2"
            onTriggered: root.modePicked("classroom")
        }
    }
    Platform.Menu {
        title: i18n.t("menu_view")
        Platform.MenuItem {
            id: darkItem
            text: i18n.t("theme_dark")
            checkable: true
            checked: root.dark
            onTriggered: root.darkPicked(darkItem.checked)
        }
        Platform.MenuItem {
            id: railItem
            text: i18n.t("collapse_rail")
            checkable: true
            checked: root.railCollapsed
            shortcut: "Ctrl+B"
            onTriggered: root.railPicked(railItem.checked)
        }
        Platform.MenuSeparator {}
        Platform.MenuItem {
            text: "Français"
            checkable: true
            checked: root.lang === "fr"
            onTriggered: root.langPicked("fr")
        }
        Platform.MenuItem {
            text: "English"
            checkable: true
            checked: root.lang === "en"
            onTriggered: root.langPicked("en")
        }
    }
}
