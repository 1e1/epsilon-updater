import QtQuick
import QtQuick.Controls.Basic

/* Scrollbar on Theme tokens — the Basic handle is palette.mid, which is a light grey on a dark
   pane. Same fade-out behaviour as the style it replaces. */
ScrollBar {
    id: control
    padding: 2

    contentItem: Rectangle {
        implicitWidth: control.interactive ? 6 : 2
        implicitHeight: control.interactive ? 6 : 2
        radius: width / 2
        color: control.pressed ? Theme.muted : Theme.lineStrong
        opacity: 0

        states: State {
            name: "active"
            when: control.policy === ScrollBar.AlwaysOn
                  || (control.active && control.size < 1.0)
            PropertyChanges { control.contentItem.opacity: 0.85 }
        }
        transitions: Transition {
            from: "active"
            SequentialAnimation {
                PauseAnimation { duration: 450 }
                NumberAnimation {
                    target: control.contentItem
                    property: "opacity"
                    to: 0
                    duration: 200
                }
            }
        }
    }
}
