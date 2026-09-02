import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

/* System tab: the firmware card (channel, version, write) with a REAL progress bar —
   Installer(progress=…) reports write/verify byte counts straight to this control. */
Flickable {
    id: root
    contentHeight: col.implicitHeight + 32
    clip: true
    ScrollBar.vertical: ScrollBar {}

    ColumnLayout {
        id: col
        x: 16; y: 16
        width: root.width - 32
        spacing: 12

        Card {
            Layout.fillWidth: true
            title: i18n.t("flash")
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 10

                Text {
                    Layout.fillWidth: true
                    text: backend.catalog.up_to_date
                          ? i18n.t("up_to_date", { v: backend.catalog.current || "" })
                          : i18n.t("update_avail", { v: backend.catalog.latest || "" })
                    color: Theme.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Segmented {
                        options: [{ key: "stable", label: "stable" }, { key: "beta", label: "beta" }]
                        current: backend.catalog.channel || "stable"
                        onPicked: (k) => backend.setChannel(k)
                    }
                    ComboBox {
                        id: versionBox
                        Layout.preferredWidth: 150
                        model: (backend.catalog.updates || []).map((u) => u.version)
                        font.pixelSize: 12
                    }
                    Item { Layout.fillWidth: true }
                    AppButton {
                        text: i18n.t("install")
                        enabled: backend.connected && backend.busy === ""
                        onClicked: backend.installFirmware(versionBox.currentText, false, false)
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "⚠  " + i18n.t("risk")
                    color: Theme.accentInk
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }

                // Determinate progress — the whole point of driving Session in-process.
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: backend.busy === "firmware"
                    spacing: 4
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: backend.progressLabel === "verify" ? i18n.t("verifying")
                                                                     : i18n.t("writing")
                            color: Theme.muted
                            font.pixelSize: 12
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: backend.progress >= 0
                                  ? Math.round(backend.progress * 100) + " %" : ""
                            color: Theme.muted
                            font.pixelSize: 12
                            font.family: Theme.mono
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 8
                        radius: 4
                        color: Theme.lineStrong
                        Rectangle {
                            width: parent.width * Math.max(0, backend.progress)
                            height: parent.height
                            radius: 4
                            color: backend.progressLabel === "verify" ? Theme.ok : Theme.accent
                            Behavior on width { NumberAnimation { duration: 80 } }
                        }
                    }
                }
            }
        }

        Card {
            Layout.fillWidth: true
            title: i18n.t("account")

            Text {
                Layout.fillWidth: true
                text: backend.auth.authenticated
                        ? i18n.t("auth_in", { d: backend.auth.expires_at || "?" })
                        : (backend.auth.expired ? i18n.t("auth_expired") : i18n.t("auth_out"))
                color: backend.auth.authenticated ? Theme.ok
                     : (backend.auth.expired ? Theme.err : Theme.muted)
                font.pixelSize: 13
                wrapMode: Text.Wrap
            }
            Text {
                Layout.fillWidth: true
                text: i18n.t("acct_purpose")
                color: Theme.muted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }

            // Signed in: nothing to do but sign out.
            AppButton {
                visible: backend.auth.authenticated
                ghost: true
                text: i18n.t("auth_logout")
                onClicked: backend.logout()
            }

            // Signed out: the built-in login (password used once, never stored)…
            ColumnLayout {
                Layout.fillWidth: true
                visible: !backend.auth.authenticated
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TextField {
                        id: emailField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 0
                        placeholderText: i18n.t("auth_email")
                        font.pixelSize: 13
                        inputMethodHints: Qt.ImhEmailCharactersOnly | Qt.ImhNoAutoUppercase
                        onAccepted: pwField.forceActiveFocus()
                    }
                    TextField {
                        id: pwField
                        Layout.fillWidth: true
                        Layout.preferredWidth: 0
                        placeholderText: i18n.t("auth_pw")
                        echoMode: TextInput.Password
                        font.pixelSize: 13
                        onAccepted: loginBtn.clicked()
                    }
                    AppButton {
                        id: loginBtn
                        text: i18n.t("auth_login")
                        enabled: emailField.text !== "" && pwField.text !== ""
                                 && backend.busy === ""
                        onClicked: {
                            backend.loginPassword(emailField.text, pwField.text)
                            pwField.text = ""
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: i18n.t("auth_pw_note")
                    color: Theme.muted
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }

                // …and the token route, folded away because it is the advanced one.
                Text {
                    text: (tokenBox.visible ? "▾  " : "▸  ") + i18n.t("auth_adv")
                    color: Theme.accentInk
                    font.pixelSize: 12
                    TapHandler { onTapped: tokenBox.visible = !tokenBox.visible }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                }
                ColumnLayout {
                    id: tokenBox
                    Layout.fillWidth: true
                    visible: false
                    spacing: 8
                    Text {
                        Layout.fillWidth: true
                        text: i18n.t("auth_hint")
                        color: Theme.muted
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        TextField {
                            id: tokenField
                            Layout.fillWidth: true
                            Layout.preferredWidth: 0
                            placeholderText: i18n.t("auth_ph")
                            font.pixelSize: 12
                            font.family: Theme.mono
                            onAccepted: tokenBtn.clicked()
                        }
                        AppButton {
                            id: tokenBtn
                            text: i18n.t("auth_save")
                            enabled: tokenField.text !== "" && backend.busy === ""
                            onClicked: {
                                backend.loginToken(tokenField.text)
                                tokenField.text = ""
                            }
                        }
                    }
                }
            }
        }
    }
}
