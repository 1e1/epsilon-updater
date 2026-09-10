import QtQuick
import QtQuick.Layouts

/* Deleting a class is destructive in two different ways, so it asks which one rather than
   offering a single "are you sure". */
Rectangle {
    id: root
    property string className: ""
    property int population: 0

    signal cancelled()
    signal chose(string mode)

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
                         { c: root.className, n: root.population })
            color: Theme.accentInk
            font.pixelSize: 13
            elide: Text.ElideRight
        }
        AppButton {
            ghost: true
            text: i18n.t("roster_cancel")
            onClicked: root.cancelled()
        }
        AppButton {
            text: i18n.t("roster_delete_class_move")
            onClicked: root.chose("move")
        }
        AppButton {
            danger: true
            text: i18n.t("roster_delete_class_purge", { n: root.population })
            onClicked: root.chose("purge")
        }
    }
}
