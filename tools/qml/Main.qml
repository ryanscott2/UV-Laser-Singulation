pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import Slicer 1.0

ApplicationWindow {
    id: root
    width: 1320
    height: 900
    minimumWidth: 1120
    minimumHeight: 760
    visible: true
    title: "Slicer  ·  UV Laser Singulation"
    color: theme.appBg

    property string initialFile: ""
    onInitialFileChanged: if (initialFile !== "") root.applyLoad(bridge.loadPath(initialFile))

    QtObject {
        id: theme
        readonly property color appBg:        "#202020"
        readonly property color cardBg:       "#2b2b2b"
        readonly property color cardStroke:   "#363636"
        readonly property color surfaceBg:    "#191919"
        readonly property color textPrimary:  "#ffffff"
        readonly property color textSecond:   "#c5c5c5"
        readonly property color textTertiary: "#8a8a8a"
        readonly property color accent:       "#4cc2ff"
        readonly property color accentText:   "#00131f"
        readonly property color danger:       "#ff99a4"
        readonly property int   radius:       8
        readonly property int   gap:          12
        readonly property int   pad:          12
        readonly property string face:        "Segoe UI Variable Text"
        readonly property string mono:        "Cascadia Mono"
    }

    readonly property var stations: ["DXF11", "DXF12", "DXF21", "DXF22"]
    readonly property var stationColor: ({
        "DXF11": "#4cc2ff", "DXF12": "#ffb951", "DXF21": "#6ccb5f", "DXF22": "#c39bf0"
    })
    readonly property var stationJig: ({
        "DXF11": "jig top-left", "DXF12": "jig top-right",
        "DXF21": "jig bottom-left", "DXF22": "jig bottom-right"
    })

    property string sourcePath: ""
    property string outputPath: ""
    property string layerSelector: ""
    property var stationOffsets: ({
        "DXF11": { "x": 0, "y": 0 }, "DXF12": { "x": 0, "y": 0 },
        "DXF21": { "x": 0, "y": 0 }, "DXF22": { "x": 0, "y": 0 }
    })

    function params() {
        return {
            "input": root.sourcePath,
            "output": root.outputPath,
            "layer": root.layerSelector,
            "cutWidth": parseFloat(widthField.text) || 50.0,
            "widthMode": widthMode.forced ? "force" : "cap",
            "clipMode": clipCombo.currentText,
            "globalX": parseFloat(offsetX.text) || 0.0,
            "globalY": parseFloat(offsetY.text) || 0.0,
            "anchors": anchorsBox.checked,
            "headerExtents": extentsBox.checked,
            "allowOutside": allowOutsideBox.checked,
            "extension": formatCombo.currentText,
            "stationOffsets": root.stationOffsets
        }
    }

    function refresh() {
        if (root.sourcePath !== "")
            bridge.refreshPreview(root.params())
    }

    function applyLoad(info) {
        if (!info || !info.ok)
            return
        root.sourcePath = info.path
        if (info.suggestedOutput !== undefined)
            root.outputPath = info.suggestedOutput
        if (info.layerRow !== undefined && info.layerRow >= 0) {
            layerCombo.currentIndex = info.layerRow
            root.layerSelector = bridge.selectorAt(info.layerRow)
        }
        root.refresh()
    }

    function setStationOffset(label, axis, value) {
        var next = JSON.parse(JSON.stringify(root.stationOffsets))
        next[label][axis] = value
        root.stationOffsets = next
        root.refresh()
    }

    Component.onCompleted: bridge.attachPreview(preview)

    FileDialog {
        id: openDialog
        title: "Select cut geometry"
        nameFilters: ["Layout files (*.dxf *.gds *.oas)", "All files (*)"]
        onAccepted: root.applyLoad(bridge.loadFile(selectedFile))
    }

    FolderDialog {
        id: folderDialog
        title: "Select output folder"
        onAccepted: root.outputPath = selectedFolder.toString().replace("file:///", "")
    }

    Dialog {
        id: saveDialog
        title: "Save dataset"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Save | Dialog.Cancel
        onAccepted: {
            bridge.saveDataset(nameField.text, root.params())
            datasetCombo.currentIndex = bridge.datasetNames.indexOf(nameField.text)
        }
        ColumnLayout {
            spacing: 8
            Label { text: "Name this dataset"; color: theme.textSecond; font.family: theme.face }
            TextField {
                id: nameField
                implicitWidth: 320
                placeholderText: "e.g. 080826 10x30 wafer"
                font.family: theme.face
            }
        }
    }

    // ------------------------------------------------------------- header

    header: Rectangle {
        height: 62
        color: theme.appBg
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1
                    color: theme.cardStroke }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: theme.pad
            anchors.rightMargin: theme.pad
            spacing: theme.gap

            ColumnLayout {
                spacing: 0
                Label {
                    text: "Four-window slicer"
                    color: theme.textPrimary
                    font.family: theme.face
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "52 mm field  ·  centers ±25.4 mm  ·  stitch 1.2 mm"
                    color: theme.textTertiary
                    font.family: theme.face
                    font.pixelSize: 12
                }
            }

            Item { Layout.fillWidth: true }

            Label {
                text: "Dataset"
                color: theme.textTertiary
                font.family: theme.face
                font.pixelSize: 12
            }
            ComboBox {
                id: datasetCombo
                implicitWidth: 220
                model: bridge.datasetNames
                displayText: currentIndex < 0 ? "none" : currentText
                onActivated: root.applyLoad(bridge.loadDataset(currentText))
            }
            Button {
                text: "Save"
                onClicked: {
                    nameField.text = datasetCombo.currentIndex >= 0 ? datasetCombo.currentText : ""
                    saveDialog.open()
                }
            }
            Button {
                text: "Delete"
                enabled: datasetCombo.currentIndex >= 0
                onClicked: {
                    bridge.deleteDataset(datasetCombo.currentText)
                    datasetCombo.currentIndex = -1
                }
            }

            Rectangle { width: 1; height: 28; color: theme.cardStroke }

            BusyIndicator {
                running: bridge.busy
                visible: bridge.busy
                implicitWidth: 22
                implicitHeight: 22
            }
            Button {
                text: "Slice into four jobs"
                highlighted: true
                enabled: root.sourcePath !== "" && !bridge.busy
                onClicked: bridge.runSlicer(root.params())
            }
        }
    }

    // --------------------------------------------------------------- body

    RowLayout {
        anchors.fill: parent
        anchors.margins: theme.pad
        spacing: theme.gap

        // ================= left column =================
        ColumnLayout {
            // The pinned card below is outside the ScrollView, so its content sets a
            // real minimum width for this column. Cap it or it squeezes the preview.
            Layout.preferredWidth: 356
            Layout.minimumWidth: 336
            Layout.maximumWidth: 356
            Layout.fillHeight: true
            spacing: theme.gap

        ScrollView {
            id: leftPane
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: leftPane.availableWidth
                spacing: theme.gap

                // ---- source
                Rectangle {
                    Layout.fillWidth: true
                    color: theme.cardBg
                    radius: theme.radius
                    border.color: theme.cardStroke
                    border.width: 1
                    implicitHeight: sourceCol.implicitHeight + theme.pad * 2
                    ColumnLayout {
                        id: sourceCol
                        anchors.fill: parent
                        anchors.margins: theme.pad
                        spacing: 8
                        Label {
                            text: "SOURCE"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 11
                            font.weight: Font.DemiBold; font.letterSpacing: 0.6
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            TextField {
                                Layout.fillWidth: true
                                text: root.sourcePath
                                placeholderText: "No file selected"
                                readOnly: true
                                font.family: theme.face
                                font.pixelSize: 12
                            }
                            Button { text: "Browse"; onClicked: openDialog.open() }
                        }
                    }
                }

                // ---- cutlines
                Rectangle {
                    Layout.fillWidth: true
                    color: theme.cardBg
                    radius: theme.radius
                    border.color: theme.cardStroke
                    border.width: 1
                    implicitHeight: cutCol.implicitHeight + theme.pad * 2
                    ColumnLayout {
                        id: cutCol
                        anchors.fill: parent
                        anchors.margins: theme.pad
                        spacing: 8

                        Label {
                            text: "CUTLINES"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 11
                            font.weight: Font.DemiBold; font.letterSpacing: 0.6
                        }

                        Label {
                            text: "Layer"; color: theme.textSecond
                            font.family: theme.face; font.pixelSize: 13
                        }
                        ComboBox {
                            id: layerCombo
                            Layout.fillWidth: true
                            model: bridge.layerModel
                            textRole: "label"
                            enabled: count > 0
                            onActivated: {
                                root.layerSelector = bridge.selectorAt(currentIndex)
                                root.refresh()
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: layerCombo.currentIndex >= 0
                            text: layerCombo.currentIndex < 0 ? "" :
                                  bridge.layerModel.data(
                                      bridge.layerModel.index(layerCombo.currentIndex, 0),
                                      Qt.UserRole + 3) || ""
                            color: theme.textTertiary
                            font.family: theme.face
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }

                        Label {
                            text: "Cutline width"; color: theme.textSecond
                            font.family: theme.face; font.pixelSize: 13
                            Layout.topMargin: 4
                        }
                        RowLayout {
                            id: widthMode
                            property bool forced: false
                            Layout.fillWidth: true
                            spacing: 6
                            TextField {
                                id: widthField
                                text: "50"
                                Layout.preferredWidth: 68
                                validator: DoubleValidator { bottom: 0.001; decimals: 3 }
                                font.family: theme.face
                                font.pixelSize: 12
                                onEditingFinished: root.refresh()
                            }
                            Label {
                                text: "µm"; color: theme.textTertiary
                                font.family: theme.face; font.pixelSize: 12
                            }
                            Item { Layout.preferredWidth: 4 }
                            Button {
                                text: "Cap at"
                                checkable: true
                                checked: !widthMode.forced
                                highlighted: !widthMode.forced
                                onClicked: { widthMode.forced = false; root.refresh() }
                            }
                            Button {
                                text: "Force to"
                                checkable: true
                                checked: widthMode.forced
                                highlighted: widthMode.forced
                                onClicked: { widthMode.forced = true; root.refresh() }
                            }
                            Item { Layout.fillWidth: true }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "Width applies to native paths only, not filled polygons."
                            color: theme.textTertiary
                            font.family: theme.face
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                // ---- output
                Rectangle {
                    Layout.fillWidth: true
                    color: theme.cardBg
                    radius: theme.radius
                    border.color: theme.cardStroke
                    border.width: 1
                    implicitHeight: outCol.implicitHeight + theme.pad * 2
                    ColumnLayout {
                        id: outCol
                        anchors.fill: parent
                        anchors.margins: theme.pad
                        spacing: 8
                        Label {
                            text: "OUTPUT"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 11
                            font.weight: Font.DemiBold; font.letterSpacing: 0.6
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            TextField {
                                Layout.fillWidth: true
                                text: root.outputPath
                                placeholderText: "Beside the input"
                                font.family: theme.face
                                font.pixelSize: 12
                                onEditingFinished: root.outputPath = text
                            }
                            Button { text: "Browse"; onClicked: folderDialog.open() }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Label {
                                text: "Format"; color: theme.textSecond
                                font.family: theme.face; font.pixelSize: 13
                            }
                            ComboBox {
                                id: formatCombo
                                model: [".dxf", ".gds", ".oas"]
                                Layout.preferredWidth: 110
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }

                // ---- options
                Rectangle {
                    Layout.fillWidth: true
                    color: theme.cardBg
                    radius: theme.radius
                    border.color: theme.cardStroke
                    border.width: 1
                    implicitHeight: optCol.implicitHeight + theme.pad * 2
                    ColumnLayout {
                        id: optCol
                        anchors.fill: parent
                        anchors.margins: theme.pad
                        spacing: 4
                        Label {
                            text: "OPTIONS"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 11
                            font.weight: Font.DemiBold; font.letterSpacing: 0.6
                            Layout.bottomMargin: 4
                        }
                        CheckBox {
                            id: anchorsBox
                            text: "Registration anchors"
                            checked: true
                            onToggled: root.refresh()
                        }
                        CheckBox {
                            id: extentsBox
                            text: "Declare window in DXF header"
                            checked: true
                        }
                        CheckBox {
                            id: allowOutsideBox
                            text: "Allow discarding outside geometry"
                            checked: false
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.topMargin: 4
                            spacing: 8
                            Label {
                                text: "Clip"; color: theme.textSecond
                                font.family: theme.face; font.pixelSize: 13
                            }
                            ComboBox {
                                id: clipCombo
                                model: ["partition", "full_window"]
                                Layout.fillWidth: true
                                onActivated: root.refresh()
                            }
                        }
                    }
                }

            }
        }

            Rectangle {
                Layout.fillWidth: true
                color: theme.cardBg
                radius: theme.radius
                border.color: theme.cardStroke
                border.width: 1
                implicitHeight: alignCol.implicitHeight + theme.pad * 2
                ColumnLayout {
                    id: alignCol
                    anchors.fill: parent
                    anchors.margins: theme.pad
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            text: "ALIGNMENT"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 11
                            font.weight: Font.DemiBold; font.letterSpacing: 0.6
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "Zero all"
                            flat: true
                            onClicked: {
                                offsetX.text = "0"; offsetY.text = "0"
                                root.stationOffsets = {
                                    "DXF11": { "x": 0, "y": 0 }, "DXF12": { "x": 0, "y": 0 },
                                    "DXF21": { "x": 0, "y": 0 }, "DXF22": { "x": 0, "y": 0 }
                                }
                                root.refresh()
                            }
                        }
                    }

                    Label {
                        text: "All four jobs"; color: theme.textSecond
                        font.family: theme.face; font.pixelSize: 13
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Label {
                            text: "X"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 12
                        }
                        TextField {
                            id: offsetX
                            text: "0"
                            Layout.preferredWidth: 74
                            validator: DoubleValidator { decimals: 3 }
                            font.family: theme.face
                            onEditingFinished: root.refresh()
                        }
                        Label {
                            text: "Y"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 12
                        }
                        TextField {
                            id: offsetY
                            text: "0"
                            Layout.preferredWidth: 74
                            validator: DoubleValidator { decimals: 3 }
                            font.family: theme.face
                            onEditingFinished: root.refresh()
                        }
                        Label {
                            text: "µm"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 12
                        }
                        Item { Layout.fillWidth: true }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: theme.cardStroke
                                Layout.topMargin: 2; Layout.bottomMargin: 2 }

                    Label {
                        text: "Per station (X, Y), on top of the above"
                        color: theme.textSecond
                        font.family: theme.face; font.pixelSize: 13
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 10
                        rowSpacing: 6
                        Repeater {
                            model: root.stations
                            delegate: RowLayout {
                                id: offsetCell
                                required property string modelData
                                Layout.fillWidth: true
                                spacing: 4
                                Rectangle {
                                    width: 3; height: 16; radius: 1.5
                                    color: root.stationColor[offsetCell.modelData]
                                }
                                Label {
                                    text: offsetCell.modelData
                                    color: theme.textSecond
                                    font.family: theme.face
                                    font.pixelSize: 11
                                    Layout.preferredWidth: 40
                                }
                                TextField {
                                    text: "0"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 46
                                    validator: DoubleValidator { decimals: 3 }
                                    font.family: theme.face
                                    font.pixelSize: 11
                                    onEditingFinished: root.setStationOffset(
                                        offsetCell.modelData, "x", parseFloat(text) || 0)
                                }
                                TextField {
                                    text: "0"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 46
                                    validator: DoubleValidator { decimals: 3 }
                                    font.family: theme.face
                                    font.pixelSize: 11
                                    onEditingFinished: root.setStationOffset(
                                        offsetCell.modelData, "y", parseFloat(text) || 0)
                                }
                            }
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: "Positive X right, positive Y up. The registration frame "
                              + "does not move."
                        color: theme.textTertiary
                        font.family: theme.face
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        // ================= centre =================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: theme.gap

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: theme.cardBg
                radius: theme.radius
                border.color: theme.cardStroke
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: theme.pad
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Label {
                            text: "PREVIEW"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 11
                            font.weight: Font.DemiBold; font.letterSpacing: 0.6
                        }
                        Item { Layout.fillWidth: true }
                        CheckBox {
                            text: "Wafer guide"
                            checked: preview.waferGuide
                            visible: preview.mode === "wafer"
                            onToggled: preview.waferGuide = checked
                        }
                        Button {
                            text: "Wafer"
                            checkable: true
                            checked: preview.mode === "wafer"
                            highlighted: preview.mode === "wafer"
                            onClicked: preview.mode = "wafer"
                        }
                        Button {
                            text: "Sliced jobs"
                            checkable: true
                            checked: preview.mode === "sliced"
                            highlighted: preview.mode === "sliced"
                            onClicked: preview.mode = "sliced"
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 6
                        color: theme.surfaceBg
                        border.color: theme.cardStroke
                        border.width: 1
                        clip: true
                        PreviewItem {
                            id: preview
                            anchors.fill: parent
                            anchors.margins: 1
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: preview.caption
                        color: theme.textTertiary
                        font.family: theme.face
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }

                    Repeater {
                        model: bridge.notes
                        delegate: RowLayout {
                            id: noteRow
                            required property string modelData
                            Layout.fillWidth: true
                            spacing: 6
                            Rectangle {
                                width: 3; height: 14; radius: 1.5
                                color: theme.danger
                                Layout.alignment: Qt.AlignVCenter
                            }
                            Label {
                                text: noteRow.modelData
                                color: theme.danger
                                font.family: theme.face
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 148
                color: theme.cardBg
                radius: theme.radius
                border.color: theme.cardStroke
                border.width: 1
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: theme.pad
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            text: "LOG"; color: theme.textTertiary
                            font.family: theme.face; font.pixelSize: 11
                            font.weight: Font.DemiBold; font.letterSpacing: 0.6
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: bridge.status
                            color: theme.textSecond
                            font.family: theme.face
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 6
                        color: theme.surfaceBg
                        border.color: theme.cardStroke
                        border.width: 1
                        clip: true
                        ScrollView {
                            anchors.fill: parent
                            anchors.margins: 8
                            TextArea {
                                id: logArea
                                readOnly: true
                                wrapMode: TextArea.NoWrap
                                color: "#a8d8a8"
                                background: null
                                font.family: theme.mono
                                font.pixelSize: 12
                            }
                        }
                    }
                }
            }
        }
    }

    Connections {
        target: bridge
        function onLogAppended(chunk) {
            logArea.text += chunk
            logArea.cursorPosition = logArea.length
        }
        function onLogCleared() { logArea.text = "" }
    }
}
