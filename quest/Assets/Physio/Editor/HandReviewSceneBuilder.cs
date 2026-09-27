using System;
using System.Collections.Generic;
using System.Linq;
using Oculus.Interaction;
using Oculus.Interaction.Grab;
using Oculus.Interaction.GrabAPI;
using Oculus.Interaction.HandGrab;
using Oculus.Interaction.Input;
using Oculus.Interaction.Locomotion;
using Oculus.Interaction.Surfaces;
using PassthroughCameraSamples.StartScene;
using Physio.Viewer;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using Object = UnityEngine.Object;

/// <summary>Builds the review scene from the pinned Meta Interaction SDK 85 components.</summary>
public static class HandReviewSceneBuilder
{
    private const string Essentials = "Packages/com.meta.xr.sdk.interaction/";
    private const string Ovr = "Packages/com.meta.xr.sdk.interaction.ovr/";
    private const string UiSet = Essentials + "Runtime/Sample/Objects/UISet/";
    private const string ButtonPath = UiSet + "Prefabs/Button/UnityUIButtonBased/PrimaryButton_IconAndLabel_UnityUIButton.prefab";
    private const string SecondaryButtonPath = UiSet + "Prefabs/Button/UnityUIButtonBased/SecondaryButton_IconAndLabel_UnityUIButton.prefab";
    private const float PanelWidth = 640f;
    private const float PanelHeight = 860f;

    public static void Configure(FixtureViewer viewer, OVRCameraRig rig)
    {
        if (viewer == null || rig == null) throw new ArgumentNullException("The viewer and camera rig are required.");
        ValidateTextResources();
        EnsureUiSetTags();
        RemoveLegacyUi(viewer);
        var interactionRig = ConfigureInteractionRig(rig);
        var material = new SerializedObject(viewer).FindProperty("boneMaterial").objectReferenceValue as Material;
        if (material == null) throw new InvalidOperationException("Assign the viewer's bone material before configuring interaction.");

        var display = CreateReplayDisplay(material);
        var panel = CreatePanel(rig, material, viewer);
        var workflow = panel.GetComponent<WorkflowPanel>();
        var capture = CreateCaptureSurfaces(rig, material, workflow);
        var handMenu = CreateHandMenu(rig, interactionRig, viewer, workflow);
        SetReferences(workflow, ("captureOverlay", capture));
        SetReferences(viewer, ("replayDisplayRoot", display), ("replayPanel", panel),
            ("interactionRigRoot", interactionRig));
        var settings = new SerializedObject(viewer);
        SetVector(settings, "viewerOffset", new Vector3(.42f, -.70f, 1.10f));
        SetVector(settings, "panelOffset", new Vector3(-.46f, -.10f, 1.15f));
        RequireProperty(settings, "initialDisplayScale").floatValue = .4f;
        settings.ApplyModifiedPropertiesWithoutUndo();
        RecordPrefabOverrides(rig.gameObject);
        RecordPrefabOverrides(display.gameObject);
        RecordPrefabOverrides(panel.gameObject);
        RecordPrefabOverrides(capture.gameObject);
        RecordPrefabOverrides(handMenu.gameObject);
    }

    private static void RemoveLegacyUi(FixtureViewer viewer)
    {
        foreach (var ui in Object.FindObjectsByType<DebugUIBuilder>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            if (ui.gameObject.scene == viewer.gameObject.scene) Object.DestroyImmediate(ui.gameObject);
        foreach (var events in Object.FindObjectsByType<EventSystem>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            if (events.gameObject.scene == viewer.gameObject.scene) Object.DestroyImmediate(events.gameObject);
        var eventRoot = new GameObject("Physio Interaction EventSystem", typeof(EventSystem), typeof(PointableCanvasModule));
        eventRoot.GetComponent<PointableCanvasModule>().ExclusiveMode = true;
    }

    private static GameObject ConfigureInteractionRig(OVRCameraRig rig)
    {
        var runtimeSettings = OVRRuntimeSettings.Instance;
        runtimeSettings.HandSkeletonVersion = OVRHandSkeletonVersion.OpenXR;
        OVRRuntimeSettings.CommitRuntimeSettings(runtimeSettings);
        var projectConfig = OVRProjectConfig.CachedProjectConfig;
        projectConfig.handTrackingSupport = OVRProjectConfig.HandTrackingSupport.ControllersAndHands;
        projectConfig.requiresSystemKeyboard = true;
        OVRProjectConfig.CommitProjectConfig(projectConfig);
        var interaction = Instantiate(Ovr + "Runtime/Prefabs/OVRInteractionComprehensive.prefab", rig.transform);
        interaction.name = "Physio Native Hand and Controller Interactions";
        var reference = interaction.GetComponentInChildren<OVRCameraRigRef>(true);
        if (reference == null) throw new InvalidOperationException("Meta's comprehensive rig is missing OVRCameraRigRef.");
        reference.InjectAllOVRCameraRigRef(rig, true);
        ConfigureStationaryRig(interaction);
        if (rig.GetComponent<OVRManager>() is OVRManager manager)
            manager.controllerDrivenHandPosesType = OVRManager.ControllerDrivenHandPosesType.ConformingToController;

        // Keep the sample's OVRHand data sources, but use the native ISDK visuals exactly as its rig wizard does.
        foreach (var hand in rig.trackingSpace.GetComponentsInChildren<OVRHand>(true))
        {
            DisableIfPresent<OVRSkeletonRenderer>(hand.gameObject);
            DisableIfPresent<OVRMesh>(hand.gameObject);
            DisableIfPresent<OVRMeshRenderer>(hand.gameObject);
            foreach (var renderer in hand.GetComponentsInChildren<Renderer>(true)) renderer.enabled = false;
        }
        foreach (var helper in rig.trackingSpace.GetComponentsInChildren<OVRControllerHelper>(true))
        {
            helper.enabled = false;
            foreach (var renderer in helper.GetComponentsInChildren<Renderer>(true)) renderer.enabled = false;
        }
        return interaction;
    }

    private static void ConfigureStationaryRig(GameObject interaction)
    {
        FindChild(interaction, "Locomotor").gameObject.SetActive(false);
        var locomotionGroups = new[] { "LocomotionHandInteractorGroup", "LocomotionControllerInteractorGroup",
            "MicroGesturesLocomotionHandInteractorGroup", "LocomotionOutput", "ScrollLocomotionGate" };
        foreach (var child in interaction.GetComponentsInChildren<Transform>(true))
            if (locomotionGroups.Contains(child.name)) child.gameObject.SetActive(false);
        foreach (var connection in interaction.GetComponentsInChildren<LocomotionEventsConnection>(true))
            connection.enabled = false;

        if (OVRRuntimeSettings.Instance.HandSkeletonVersion != OVRHandSkeletonVersion.OpenXR
            || OVRProjectConfig.CachedProjectConfig.handTrackingSupport != OVRProjectConfig.HandTrackingSupport.ControllersAndHands)
            throw new InvalidOperationException("SDK 85 requires OpenXR hand skeletons and hands/controllers enabled.");
        if (interaction.GetComponentsInChildren<FirstPersonLocomotor>(true).Any(item => item.isActiveAndEnabled)
            || interaction.GetComponentsInChildren<TunnelingEffect>(true).Any(item => item.isActiveAndEnabled)
            || interaction.GetComponentsInChildren<LocomotionEventsConnection>(true).Any(item => item.isActiveAndEnabled))
            throw new InvalidOperationException("Stationary replay must not contain active locomotion or tunneling components.");
        Debug.Log("PHYSIO_NATIVE_RIG_VALIDATED: OpenXR hands, controllers enabled, locomotion and tunneling disabled");
    }

    private static void DisableIfPresent<T>(GameObject target) where T : Behaviour
    {
        if (target.TryGetComponent<T>(out var component)) component.enabled = false;
    }

    private static Transform CreateReplayDisplay(Material material)
    {
        var display = new GameObject("Replay Display — pinch handles to move; two hands to resize").transform;
        display.localScale = Vector3.one * .4f;
        var collider = display.gameObject.AddComponent<BoxCollider>();
        collider.center = new Vector3(0f, .9f, 0f);
        collider.size = new Vector3(1.1f, 1.9f, .65f);
        AddGrabInteractions(display.gameObject, display, collider, allowScale: true);

        var leftHandle = CreateHandle(display, "Left replay grab handle", new Vector3(-.46f, .9f, -.35f),
            new Vector3(.11f, .36f, .11f), material);
        var rightHandle = CreateHandle(display, "Right replay grab handle", new Vector3(.46f, .9f, -.35f),
            new Vector3(.11f, .36f, .11f), material);
        var grab = display.GetComponent<Grabbable>();
        AddRayGrabInteraction(leftHandle, leftHandle.GetComponent<Collider>(), grab);
        AddRayGrabInteraction(rightHandle, rightHandle.GetComponent<Collider>(), grab);
        AddGrabFeedback(display.gameObject, leftHandle.GetComponent<Renderer>(), rightHandle.GetComponent<Renderer>());
        return display;
    }

    private static HandReplayPanel CreatePanel(OVRCameraRig rig, Material material, FixtureViewer viewer)
    {
        // Keep persistence and result loading active while only the visible workspace is hidden.
        var root = new GameObject("Physio Workspace");
        var panel = root.AddComponent<HandReplayPanel>();
        var workflow = root.AddComponent<WorkflowPanel>();
        var visuals = CreateSurface("Patient and assessment details", rig, PanelWidth, PanelHeight, out var backplate);
        visuals.transform.SetParent(root.transform, false);

        var navigation = CreateRow(backplate, "Navigation");
        var back = CreateButton(navigation, "Back");
        var brand = CreateText(navigation, "Brand", "PHYSIO", 24f, 56f);
        brand.alignment = TextAlignmentOptions.Center;
        brand.color = new Color(.48f, .87f, 1f);
        var options = CreateButton(navigation, "Options");
        var context = CreateText(backplate, "Patient and test", "LOCAL PATIENTS · QUEST 3", 23f, 56f);
        context.color = new Color(.72f, .79f, .87f);
        var heading = CreateText(backplate, "Page heading", "Your patients", 30f, 44f);
        heading.fontStyle = FontStyles.Bold;
        var content = new GameObject("Page content", typeof(RectTransform), typeof(VerticalLayoutGroup), typeof(LayoutElement));
        content.transform.SetParent(backplate, false);
        var contentLayout = content.GetComponent<VerticalLayoutGroup>();
        contentLayout.spacing = 8f;
        contentLayout.childControlHeight = contentLayout.childControlWidth = true;
        contentLayout.childForceExpandHeight = false;
        contentLayout.childForceExpandWidth = true;
        content.GetComponent<LayoutElement>().flexibleHeight = 1;
        var body = CreateText(content.transform, "Page detail", "", 24f, 150f);
        body.overflowMode = TextOverflowModes.Overflow;
        var previews = new GameObject("Evidence previews", typeof(RectTransform), typeof(VerticalLayoutGroup), typeof(LayoutElement));
        previews.transform.SetParent(content.transform, false);
        SetLayout(previews, 200f);
        var previewsLayout = previews.GetComponent<VerticalLayoutGroup>();
        previewsLayout.spacing = 8;
        previewsLayout.childControlHeight = previewsLayout.childControlWidth = true;
        previewsLayout.childForceExpandHeight = false;
        var videos = CreateRow(previews.transform, "Original and amplified");
        SetLayout(videos.gameObject, 140f);
        var original = CreatePreview(videos, "Original recording");
        var amplified = CreatePreview(videos, "Amplified recording");
        var previewCaption = CreateText(previews.transform, "Evidence labels", "ORIGINAL", 22f, 52f);
        var list = new Button[4];
        for (var i = 0; i < list.Length; i++)
        {
            list[i] = CreateButton(content.transform, "List item " + (i + 1));
            ButtonLabel(list[i]).alignment = TextAlignmentOptions.MidlineLeft;
            ButtonLabel(list[i]).rectTransform.offsetMin = new Vector2(20f, 4f);
        }

        var replayRoot = CreateSurface("Floating replay timeline", rig, 620f, 290f, out var replayContent);
        // This surface stays outside the workspace visual hierarchy and is placed once when opened.
        var title = CreateText(replayContent, "Replay title", "SOURCE REPLAY", 22f, 0f);
        title.gameObject.SetActive(false);
        var replayStatus = CreateText(replayContent, "Replay provenance", "", 22f, 28f);
        var sliderRoot = Instantiate(UiSet + "Prefabs/Slider/LargeSlider.prefab", replayContent);
        SetLayout(sliderRoot, 48f);
        var slider = sliderRoot.GetComponentInChildren<Slider>(true);
        if (slider == null) throw new InvalidOperationException("Meta UI Set slider missing.");
        var time = CreateText(replayContent, "Source time", "0.00s", 24f, 26f);
        var playback = CreateRow(replayContent, "Playback");
        var previous = CreateButton(playback, "Frame −");
        var play = CreateButton(playback, "Play", primary: true);
        var next = CreateButton(playback, "Frame +");
        var speed = CreateButton(playback, "Speed 1×");
        var timing = CreateRow(replayContent, "Direction");
        var reverse = CreateButton(timing, "Play backward");
        var restart = CreateButton(timing, "Restart");
        var replaySettings = new SerializedObject(panel);
        RequireProperty(replaySettings, "externalLayout").boolValue = true;
        replaySettings.ApplyModifiedPropertiesWithoutUndo();
        var status = CreateText(backplate, "Operation status", "", 23f, 64f);
        status.color = new Color(.72f, .87f, 1f);
        status.overflowMode = TextOverflowModes.Overflow;
        var actions = CreateRow(backplate, "Page actions");
        var primary = CreateButton(actions, "New patient", true);
        var secondary = CreateButton(actions, "Next");
        var help = CreateText(backplate, "Placement help", "Drag the bar to move · Menu for options", 20f, 26f);
        help.color = new Color(.72f, .79f, .87f);
        FinishSurface(visuals, material, PanelHeight, root.transform);
        FinishSurface(replayRoot, material, 290f);
        SetReferences(panel, ("playPauseButton", play), ("reverseButton", reverse),
            ("previousFrameButton", previous), ("nextFrameButton", next), ("restartButton", restart),
            ("speedButton", speed), ("seekSlider", slider), ("titleLabel", title),
            ("statusLabel", replayStatus), ("timeLabel", time), ("playPauseLabel", ButtonLabel(play)),
            ("reverseLabel", ButtonLabel(reverse)), ("speedLabel", ButtonLabel(speed)),
            ("timelineRoot", replayRoot.transform), ("head", rig.centerEyeAnchor));
        SetReferences(workflow, ("viewer", viewer), ("heading", heading), ("context", context), ("body", body),
            ("status", status), ("back", back), ("options", options), ("primary", primary),
            ("secondary", secondary), ("replayControls", replayRoot), ("preview", original),
            ("amplifiedPreview", amplified), ("previewRoot", previews), ("previewCaption", previewCaption),
            ("workspaceVisuals", visuals));
        var workflowSettings = new SerializedObject(workflow);
        var rowProperty = RequireProperty(workflowSettings, "rows");
        rowProperty.arraySize = list.Length;
        for (var i = 0; i < list.Length; i++) rowProperty.GetArrayElementAtIndex(i).objectReferenceValue = list[i];
        workflowSettings.ApplyModifiedPropertiesWithoutUndo();
        LayoutRebuilder.ForceRebuildLayoutImmediate(backplate);
        RecordPrefabOverrides(replayRoot);
        return panel;
    }

    private static SpatialCaptureOverlay CreateCaptureSurfaces(OVRCameraRig rig, Material material, WorkflowPanel workflow)
    {
        var root = new GameObject("Spatial Capture Controls");
        var overlay = root.AddComponent<SpatialCaptureOverlay>();
        var guidance = CreateSurface("Capture guidance — drag to place beside the patient", rig, 540f, 344f, out var content);
        guidance.transform.SetParent(root.transform, false);
        var context = CreateText(content, "Capture test and duration", "SAME MOVEMENT · EACH VIEW", 22f, 52f);
        context.overflowMode = TextOverflowModes.Overflow;
        context.color = new Color(.72f, .83f, .9f);
        var title = CreateText(content, "Patient position instruction", "Start at the patient's RIGHT side", 28f, 56f);
        title.fontStyle = FontStyles.Bold;
        title.overflowMode = TextOverflowModes.Overflow;
        var steps = CreateText(content, "Four separate capture views", "RIGHT   →   FRONT   →   BACK   →   LEFT", 22f, 32f);
        steps.color = new Color(.48f, .87f, 1f);
        var status = CreateText(content, "Capture state", "Confirm your position before recording.", 23f, 72f);
        status.overflowMode = TextOverflowModes.Overflow;
        var actions = CreateRow(content, "Capture navigation");
        var retake = CreateButton(actions, "Retake last view");
        var workspace = CreateButton(actions, "Options");
        AddButtonIcon(workspace, "settings.png");

        var dock = CreateSurface("Floating record control", rig, 360f, 138f, out var dockContent);
        dock.transform.SetParent(root.transform, false);
        var recordTime = CreateText(dockContent, "Capture elapsed and duration", "READY · 10 SECOND TAKE", 22f, 28f);
        recordTime.alignment = TextAlignmentOptions.Center;
        recordTime.color = new Color(.72f, .87f, 1f);
        var record = CreateButton(dockContent, "Record right", true);
        ButtonLabel(record).fontSize = 28f;
        FinishSurface(guidance, material, 344f);
        FinishSurface(dock, material, 138f);
        SetReferences(overlay, ("workflow", workflow), ("head", rig.centerEyeAnchor),
            ("guidanceRoot", guidance), ("guidanceTitle", title), ("guidanceContext", context),
            ("guidanceSteps", steps), ("guidanceStatus", status), ("recordDock", dock),
            ("recordButton", record), ("recordLabel", ButtonLabel(record)), ("recordTime", recordTime),
            ("retakeButton", retake), ("workspaceButton", workspace));
        return overlay;
    }

    private static HandSpatialMenu CreateHandMenu(OVRCameraRig rig, GameObject interaction, FixtureViewer viewer, WorkflowPanel workflow)
    {
        var root = new GameObject("Hand shortcuts");
        var menu = root.AddComponent<HandSpatialMenu>();
        // SDK 85 keeps native Hand providers on the interaction roots, not the visual LeftHand/RightHand objects.
        var left = FindChild(interaction, "LeftInteractions").GetComponent<Hand>();
        var right = FindChild(interaction, "RightInteractions").GetComponent<Hand>();
        if (left == null || right == null) throw new InvalidOperationException("Native left and right hand data are required for hand shortcuts.");
        var hand = root.AddComponent<DominantHandRef>();
        hand.InjectAllDominantHandRef(left, right);
        hand.SelectDominant = false;
        var anchor = new GameObject("Native non-dominant wrist anchor");
        anchor.transform.SetParent(root.transform, false);
        var joint = anchor.AddComponent<HandJoint>();
        joint.InjectHand(hand);
        joint.HandJointId = HandJointId.HandWristRoot;
        // The OpenXR offset/orientation matches Meta's current PalmMenu attachment.
        joint.LocalPositionOffset = new Vector3(-.001f, 0, .08f);
        joint.RotationOffset = new Quaternion(.5f, -.5f, .5f, .5f);
        joint.MirrorOffsetsForLeftHand = true;
        var jointSettings = new SerializedObject(joint);
        RequireProperty(jointSettings, "_freezeRotationZ").boolValue = true;
        jointSettings.ApplyModifiedPropertiesWithoutUndo();
        var handVisuals = new GameObject("Hand shortcut visuals");
        handVisuals.transform.SetParent(anchor.transform, false);
        var launcher = CreateSurface("Hand menu launcher", rig, 160f, 88f, out var launcherContent);
        launcher.transform.SetParent(handVisuals.transform, false);
        launcher.transform.localScale = Vector3.one * .5f;
        var launcherButton = CreateButton(launcherContent, "Menu", true);
        var shelf = CreateSurface("Hand shortcut shelf", rig, 440f, 108f, out var shelfContent);
        shelf.transform.SetParent(handVisuals.transform, false);
        shelf.transform.localPosition = new Vector3(0, -.074f, 0);
        shelf.transform.localScale = Vector3.one * .5f;
        var buttons = CreateRow(shelfContent, "Hand actions");
        var capture = CreateButton(buttons, "Capture");
        var replay = CreateButton(buttons, "Replay");
        var options = CreateButton(buttons, "Options");
        foreach (var button in new[] { capture, replay, options }) ButtonLabel(button).fontSize = 22f;
        AddButtonIcon(replay, "play.png");
        AddButtonIcon(options, "settings.png");
        launcher.GetComponent<UIThemeManager>().ApplyCurrentTheme();
        shelf.GetComponent<UIThemeManager>().ApplyCurrentTheme();
        LayoutRebuilder.ForceRebuildLayoutImmediate(launcherContent);
        LayoutRebuilder.ForceRebuildLayoutImmediate(shelfContent);
        SetReferences(menu, ("viewer", viewer), ("workflow", workflow), ("handRoot", handVisuals),
            ("launcherButton", launcherButton), ("shelf", shelf), ("captureButton", capture),
            ("replayButton", replay), ("optionsButton", options), ("hand", hand), ("head", rig.centerEyeAnchor));
        shelf.SetActive(false);
        handVisuals.SetActive(false);
        return menu;
    }

    private static GameObject CreateSurface(string name, OVRCameraRig rig, float width, float height, out RectTransform backplate)
    {
        var root = Instantiate(UiSet + "Prefabs/Backplate/EmptyUIBackplateWithCanvas.prefab", null);
        root.name = name;
        var canvas = FindChild(root, "CanvasRoot").GetComponent<RectTransform>();
        canvas.localScale = Vector3.one * .001f;
        canvas.sizeDelta = new Vector2(width, height);
        canvas.GetComponent<Canvas>().worldCamera = rig.centerEyeAnchor.GetComponent<Camera>();
        DisableIfPresent<HorizontalLayoutGroup>(canvas.gameObject);
        backplate = FindChild(root, "UIBackplate").GetComponent<RectTransform>();
        backplate.anchorMin = backplate.anchorMax = backplate.pivot = new Vector2(.5f, .5f);
        backplate.anchoredPosition = Vector2.zero;
        backplate.sizeDelta = new Vector2(width, height);
        var layout = backplate.GetComponent<VerticalLayoutGroup>();
        layout.padding = new RectOffset(16, 16, 16, 16);
        layout.spacing = 8f;
        layout.childControlHeight = layout.childControlWidth = true;
        layout.childForceExpandHeight = false;
        layout.childForceExpandWidth = true;
        ConfigureTheme(root);
        return root;
    }

    private static void FinishSurface(GameObject root, Material material, float height, Transform target = null)
    {
        root.GetComponent<UIThemeManager>().ApplyCurrentTheme();
        var handle = CreateHandle(root.transform, "Drag to move", new Vector3(0, -height * .0005f - .022f, -.018f),
            new Vector3(.18f, .025f, .04f), material);
        AddGrabInteractions(handle, target != null ? target : root.transform, handle.GetComponent<Collider>(), allowScale: false);
        AddGrabFeedback(handle, handle.GetComponent<Renderer>());
        LayoutRebuilder.ForceRebuildLayoutImmediate(FindChild(root, "UIBackplate").GetComponent<RectTransform>());
    }

    private static void AddButtonIcon(Button button, string fileName)
    {
        var icon = FindChild(button.gameObject, "Icon");
        icon.gameObject.SetActive(true);
        var image = icon.GetComponent<Image>();
        image.sprite = LoadRequired<Sprite>(Essentials + "Runtime/Sample/Textures/Icons/" + fileName);
        image.raycastTarget = false;
        image.preserveAspect = true;
        var rect = image.rectTransform;
        rect.anchorMin = rect.anchorMax = new Vector2(0, .5f);
        rect.anchoredPosition = new Vector2(24f, 0);
        rect.sizeDelta = new Vector2(24f, 24f);
        ButtonLabel(button).rectTransform.offsetMin = new Vector2(42f, 4f);
    }

    private static RawImage CreatePreview(Transform parent, string name)
    {
        var frame = new GameObject(name + " frame", typeof(RectTransform), typeof(LayoutElement));
        frame.transform.SetParent(parent, false);
        frame.GetComponent<LayoutElement>().flexibleWidth = 1;
        var root = new GameObject(name, typeof(RectTransform), typeof(RawImage), typeof(AspectRatioFitter));
        root.transform.SetParent(frame.transform, false);
        var image = root.GetComponent<RawImage>();
        image.color = Color.white;
        image.raycastTarget = false;
        var fit = root.GetComponent<AspectRatioFitter>();
        fit.aspectMode = AspectRatioFitter.AspectMode.FitInParent;
        fit.aspectRatio = 16f / 9f;
        return image;
    }

    private static void AddGrabInteractions(GameObject source, Transform target, Collider collider, bool allowScale)
    {
        var body = source.AddComponent<Rigidbody>();
        body.isKinematic = true;
        body.useGravity = false;
        var grab = source.AddComponent<Grabbable>();
        grab.MaxGrabPoints = allowScale ? 2 : 1;
        grab.InjectOptionalTargetTransform(target);
        grab.InjectOptionalRigidbody(body);
        grab.InjectOptionalThrowWhenUnselected(false);
        var transformer = source.AddComponent<GrabFreeTransformer>();
        if (allowScale)
        {
            var axis = new TransformerUtils.ConstrainedAxis
            {
                ConstrainAxis = true,
                AxisRange = new TransformerUtils.FloatRange { Min = .5f, Max = 3f }
            };
            transformer.InjectOptionalScaleConstraints(new TransformerUtils.ScaleConstraints
                { ConstraintsAreRelative = true, XAxis = axis, YAxis = axis, ZAxis = axis });
        }
        grab.InjectOptionalOneGrabTransformer(transformer);
        grab.InjectOptionalTwoGrabTransformer(transformer);
        var controllerGrab = source.AddComponent<GrabInteractable>();
        controllerGrab.InjectRigidbody(body);
        controllerGrab.InjectOptionalPointableElement(grab);
        controllerGrab.ResetGrabOnGrabsUpdated = false;
        var handGrab = source.AddComponent<HandGrabInteractable>();
        handGrab.InjectAllHandGrabInteractable(GrabTypeFlags.All, body,
            GrabbingRule.DefaultPinchRule, GrabbingRule.DefaultPalmRule);
        handGrab.InjectOptionalPointableElement(grab);
        handGrab.ResetGrabOnGrabsUpdated = false;
        AddRayGrabInteraction(source, collider, grab);
    }

    private static void AddRayGrabInteraction(GameObject source, Collider collider, Grabbable grab)
    {
        // The SDK Quick Action uses this template and its native MoveFromTargetProvider for ray dragging.
        var rayObject = Instantiate(Essentials + "Editor/QuickActions/Templates/Template_RayGrabInteraction.prefab", source.transform);
        var ray = rayObject.GetComponent<RayInteractable>();
        var surface = rayObject.AddComponent<ColliderSurface>();
        surface.InjectCollider(collider);
        ray.InjectSurface(surface);
        ray.InjectOptionalPointableElement(grab);
    }

    private static void AddGrabFeedback(GameObject source, params Renderer[] renderers)
    {
        var interactables = source.GetComponentsInChildren<MonoBehaviour>(true).OfType<IInteractableView>().ToList();
        var group = source.AddComponent<InteractableGroupView>();
        group.InjectAllInteractableGroupView(interactables);
        var materialProperties = source.AddComponent<MaterialPropertyBlockEditor>();
        materialProperties.Renderers = new List<Renderer>(renderers);
        var visual = source.AddComponent<InteractableColorVisual>();
        visual.InjectAllInteractableColorVisual(group, materialProperties);
        visual.InjectOptionalNormalColorState(new InteractableColorVisual.ColorState { Color = new Color(.3f, .95f, 1f) });
        visual.InjectOptionalHoverColorState(new InteractableColorVisual.ColorState { Color = Color.white });
        visual.InjectOptionalSelectColorState(new InteractableColorVisual.ColorState { Color = new Color(.55f, 1f, .72f) });
    }

    private static GameObject CreateHandle(Transform parent, string name, Vector3 position, Vector3 scale, Material material)
    {
        var handle = GameObject.CreatePrimitive(PrimitiveType.Cube);
        handle.name = name;
        handle.transform.SetParent(parent, false);
        handle.transform.localPosition = position;
        handle.transform.localScale = scale;
        handle.GetComponent<Renderer>().sharedMaterial = material;
        return handle;
    }

    private static Transform CreateRow(Transform parent, string name)
    {
        var row = new GameObject(name, typeof(RectTransform), typeof(HorizontalLayoutGroup), typeof(LayoutElement));
        row.transform.SetParent(parent, false);
        var layout = row.GetComponent<HorizontalLayoutGroup>();
        layout.spacing = 8f;
        layout.childControlWidth = true;
        layout.childControlHeight = true;
        layout.childForceExpandWidth = true;
        layout.childForceExpandHeight = true;
        SetLayout(row, 56f);
        return row.transform;
    }

    private static Button CreateButton(Transform parent, string title, bool primary = false)
    {
        var root = Instantiate(primary ? ButtonPath : SecondaryButtonPath, parent);
        root.name = title;
        var button = root.GetComponent<Button>();
        if (button == null) throw new InvalidOperationException("Meta UI Set button is missing its Unity Button.");
        var label = ButtonLabel(button);
        label.text = title;
        label.fontSize = 24f;
        label.richText = false;
        label.enableAutoSizing = false;
        foreach (var child in root.GetComponentsInChildren<Transform>(true))
            if (child.name == "Subtitle" || child.name == "Icon" || child.name == "Gap") child.gameObject.SetActive(false);
        ExpandButtonLabel(button, label);
        SetLayout(root, 56f);
        return button;
    }

    private static void ExpandButtonLabel(Button button, TMP_Text label)
    {
        // Preserve the UI Set animation paths while replacing its fixed 40-pixel label layout.
        for (var current = label.transform; current != button.transform; current = current.parent)
        {
            if (current == null) throw new InvalidOperationException("UI Set label is outside its button hierarchy.");
            foreach (var layout in current.GetComponents<LayoutGroup>()) layout.enabled = false;
            DisableIfPresent<ContentSizeFitter>(current.gameObject);
            var rect = (RectTransform)current;
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(.5f, .5f);
            rect.anchoredPosition = Vector2.zero;
            rect.sizeDelta = Vector2.zero;
        }
        foreach (var layout in button.GetComponents<LayoutGroup>()) layout.enabled = false;
        DisableIfPresent<ContentSizeFitter>(button.gameObject);
        label.rectTransform.offsetMin = new Vector2(10f, 4f);
        label.rectTransform.offsetMax = new Vector2(-10f, -4f);
        label.alignment = TextAlignmentOptions.Center;
    }

    private static TMP_Text ButtonLabel(Button button) => button.GetComponentsInChildren<TMP_Text>(true)
        .FirstOrDefault(label => label.name == "Label")
        ?? throw new InvalidOperationException("Meta UI Set button has no Label text.");

    private static TMP_Text CreateText(Transform parent, string name, string text, float fontSize, float height)
    {
        var root = new GameObject(name, typeof(RectTransform), typeof(TextMeshProUGUI), typeof(LayoutElement));
        root.transform.SetParent(parent, false);
        var label = root.GetComponent<TextMeshProUGUI>();
        var template = LoadRequired<GameObject>(ButtonPath).GetComponentsInChildren<TMP_Text>(true).First();
        label.font = template.font;
        label.fontSharedMaterial = template.fontSharedMaterial;
        label.fontSize = fontSize;
        label.text = text;
        label.color = Color.white;
        label.raycastTarget = false;
        label.richText = false;
        label.overflowMode = TextOverflowModes.Ellipsis;
        SetLayout(root, height);
        return label;
    }

    private static void SetLayout(GameObject target, float height)
    {
        var element = target.GetComponent<LayoutElement>() ?? target.AddComponent<LayoutElement>();
        element.minHeight = height;
        element.preferredHeight = height;
        element.flexibleWidth = 1f;
    }

    private static void ConfigureTheme(GameObject panel)
    {
        var theme = LoadRequired<UITheme>(UiSet + "Themes/UIThemeQuest_Dark.asset");
        var settings = new SerializedObject(panel.GetComponent<UIThemeManager>());
        var themes = settings.FindProperty("_themes");
        themes.arraySize = 1;
        themes.GetArrayElementAtIndex(0).objectReferenceValue = theme;
        settings.FindProperty("_currentThemeIndex").intValue = 0;
        settings.ApplyModifiedPropertiesWithoutUndo();
    }

    private static void ValidateTextResources()
    {
        // Essentials is a project asset dependency. ImportPackage completes asynchronously,
        // so importing it during a batch build can leave text resources unavailable.
        const string settingsPath = "Assets/TextMesh Pro/Resources/TMP Settings.asset";
        const string fontPath = "Assets/TextMesh Pro/Resources/Fonts & Materials/LiberationSans SDF.asset";
        var settings = AssetDatabase.LoadAssetAtPath<TMP_Settings>(settingsPath);
        var font = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(fontPath);
        if (settings == null || font == null || font.material == null || font.material.shader == null)
            throw new InvalidOperationException("TMP Essentials assets are missing or incomplete. Import the official TMP Essential Resources into this Unity project's Assets folder before building.");
    }

    private static void EnsureUiSetTags()
    {
        var required = new[] { "QDSUIPrimaryButton", "QDSUISecondaryButton", "QDSUIBorderlessButton",
            "QDSUIDestructiveButton", "QDSUIToggleButton", "QDSUIToggleBorderlessButton", "QDSUIToggleSwitch",
            "QDSUIToggleCheckboxRadio", "QDSUITextInputField", "QDSUIIcon", "QDSUIAccentColor", "QDSUISharedThemeColor",
            "QDSUISection", "QDSUITooltip", "QDSUIBackplate", "QDSUIBackplateGradient", "QDSUITextInvertedColor",
            "QDSUITextSecondaryColor", "QDSUITextSecondaryInvertedColor" };
        var settings = new SerializedObject(AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/TagManager.asset")[0]);
        var tags = settings.FindProperty("tags");
        var existing = Enumerable.Range(0, tags.arraySize).Select(i => tags.GetArrayElementAtIndex(i).stringValue).ToHashSet();
        foreach (var tag in required.Where(tag => !existing.Contains(tag)))
        {
            var index = tags.arraySize;
            tags.InsertArrayElementAtIndex(index);
            tags.GetArrayElementAtIndex(index).stringValue = tag;
        }
        settings.ApplyModifiedPropertiesWithoutUndo();
    }

    private static void SetReferences(Object target, params (string Name, Object Value)[] references)
    {
        var settings = new SerializedObject(target);
        foreach (var reference in references)
        {
            var property = RequireProperty(settings, reference.Name);
            property.objectReferenceValue = reference.Value;
        }
        settings.ApplyModifiedPropertiesWithoutUndo();
    }

    private static void SetVector(SerializedObject settings, string name, Vector3 value)
    {
        RequireProperty(settings, name).vector3Value = value;
    }

    private static SerializedProperty RequireProperty(SerializedObject settings, string name) => settings.FindProperty(name)
        ?? throw new InvalidOperationException($"Missing serialized field {settings.targetObject.GetType().Name}.{name}.");

    private static Transform FindChild(GameObject root, string name) => root.GetComponentsInChildren<Transform>(true)
        .FirstOrDefault(child => child.name == name)
        ?? throw new InvalidOperationException($"Meta UI Set prefab is missing {name}.");

    private static GameObject Instantiate(string path, Transform parent)
    {
        var instance = (GameObject)PrefabUtility.InstantiatePrefab(LoadRequired<GameObject>(path));
        if (parent != null) instance.transform.SetParent(parent, false);
        return instance;
    }

    private static T LoadRequired<T>(string path) where T : Object => AssetDatabase.LoadAssetAtPath<T>(path)
        ?? throw new InvalidOperationException($"Required Meta SDK 85 asset is unavailable: {path}");

    private static void RecordPrefabOverrides(GameObject root)
    {
        foreach (var child in root.GetComponentsInChildren<Transform>(true))
        {
            if (PrefabUtility.IsPartOfPrefabInstance(child.gameObject))
                PrefabUtility.RecordPrefabInstancePropertyModifications(child.gameObject);
            foreach (var component in child.GetComponents<Component>())
                if (component != null && PrefabUtility.IsPartOfPrefabInstance(component))
                    PrefabUtility.RecordPrefabInstancePropertyModifications(component);
        }
    }
}
