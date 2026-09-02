import QtQuick

/* The 4-state memory bar: one segment per kept item, 2 px apart, then the free tail.

   Laid out inside a plain Item with explicit x/width rather than a Row: a positioner would
   derive its implicitWidth from children whose width binds back to the container, which is a
   binding loop (and a stack overflow, not a warning, once it is nested in a Layout). */
Column {
    id: root
    property var plan: ({})
    property var segments: plan.segments || []
    spacing: 8

    Item {
        id: track
        width: root.width
        height: 10

        readonly property int gap: 2
        readonly property real usable: Math.max(0, width - gap * root.segments.length)

        Repeater {
            model: root.segments
            delegate: Rectangle {
                required property var modelData
                required property int index
                readonly property real span: track.usable * Math.max(0, modelData.w) / 100
                x: {
                    let acc = 0
                    for (let i = 0; i < index; i++)
                        acc += track.usable * Math.max(0, root.segments[i].w) / 100 + track.gap
                    return acc
                }
                width: Math.max(3, span)
                height: track.height
                radius: 3
                color: Theme.statusColor(modelData.status)
                Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
            }
        }

        Rectangle {  // free tail
            x: {
                let acc = 0
                for (let i = 0; i < root.segments.length; i++)
                    acc += track.usable * Math.max(0, root.segments[i].w) / 100 + track.gap
                return acc
            }
            width: Math.max(0, track.width - x)
            height: track.height
            radius: 3
            color: Theme.lineStrong
        }
    }

    Row {
        spacing: 14
        Repeater {
            model: [
                { c: Theme.ok,         k: "leg_un" },
                { c: Theme.accent,     k: "leg_rw" },
                { c: Theme.blue,       k: "leg_new" },
                { c: Theme.lineStrong, k: "leg_free" }
            ]
            delegate: Row {
                required property var modelData
                spacing: 5
                Rectangle {
                    width: 8; height: 8; radius: 2
                    color: modelData.c
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: i18n.t(modelData.k)
                    color: Theme.muted
                    font.pixelSize: 11
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }
}
