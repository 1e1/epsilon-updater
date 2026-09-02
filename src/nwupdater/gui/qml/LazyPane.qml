import QtQuick

/* A pane that is built the first time it is shown, and kept afterwards.

   Building every pane up front costs memory for views the user may never open; unloading them
   again would throw away scroll position and focus, which is the one thing this port set out to
   fix. So: load once, on first sight, then hold. */
Loader {
    id: root
    property bool shown: false
    active: false
    asynchronous: false
    onShownChanged: if (shown) active = true
    Component.onCompleted: if (shown) active = true
}
