using System;
using System.IO;
using System.Linq;
using PassthroughCameraSamples.StartScene;
using Physio.Replay;
using Physio.Viewer;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class FixtureBuild
{
    private const string ScenePath = "Assets/Physio/Scenes/FixtureViewer.unity";
    private const string SampleScene = "Assets/PassthroughCameraApiSamples/StartScene/StartScene.unity";

    [MenuItem("Physio/Build Quest fixture viewer")]
    public static void Build()
    {
        if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
        Environment.SetEnvironmentVariable("BEE_BUILD_THREADS", "6");
        ValidateFixture();
        ValidateDemo();
        CreateScene();
        ConfigurePlayer();
        var output = Path.GetFullPath("Builds/PhysioFixture.apk");
        Directory.CreateDirectory(Path.GetDirectoryName(output));
        var report = BuildPipeline.BuildPlayer(new[] { ScenePath }, output,
            BuildTarget.Android, BuildOptions.Development | BuildOptions.CleanBuildCache);
        if (report.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException($"Fixture build failed: {report.summary.result}, {report.summary.totalErrors} errors.");
        Debug.Log($"PHYSIO_FIXTURE_APK: {output} ({new FileInfo(output).Length} bytes)");
    }

    private static void ValidateFixture()
    {
        var replay = ReadReplay("Fixture");
        if (!replay.Synthetic || replay.FrameCount != 4 || replay.VertexCount != 4 || replay.JointCount != 3)
            throw new InvalidDataException("The fixture build requires the labelled four-frame synthetic fixture.");
        Debug.Log("PHYSIO_FIXTURE_VALIDATED: synthetic, 4 frames, 4 vertices, 3 joints");
    }

    private static void ValidateDemo()
    {
        var replay = ReadReplay("Demo");
        if (!replay.Synthetic || replay.FrameCount != 121 || replay.JointCount != 21
            || replay.Timeline.EndTime != 6)
            throw new InvalidDataException("The interaction build requires the labelled six-second authored mannequin.");
        Debug.Log("PHYSIO_DEMO_VALIDATED: synthetic, 121 frames, 21 joints, 6 seconds");
    }

    private static ReplayData ReadReplay(string name)
    {
        var directory = Path.Combine(Application.dataPath, "Resources/Physio", name);
        return ReplayImporter.Parse(File.ReadAllBytes(Path.Combine(directory, "replay_manifest.json")),
            File.ReadAllBytes(Path.Combine(directory, "mesh_triangles.bytes")),
            File.ReadAllBytes(Path.Combine(directory, "mesh_vertices.bytes")),
            File.ReadAllBytes(Path.Combine(directory, "skeleton_joints.bytes")));
    }

    private static void CreateScene()
    {
        var scene = EditorSceneManager.OpenScene(SampleScene, OpenSceneMode.Single);
        var removed = new[] { "StartMenu", "overlay", "loadingText", "CompositorLayerLoadingScreen" };
        foreach (var root in scene.GetRootGameObjects().Where(root => removed.Contains(root.name)))
            UnityEngine.Object.DestroyImmediate(root);
        foreach (var menu in UnityEngine.Object.FindObjectsByType<ReturnToStartScene>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            UnityEngine.Object.DestroyImmediate(menu.gameObject);

        var rig = UnityEngine.Object.FindFirstObjectByType<OVRCameraRig>();
        if (rig == null) throw new InvalidOperationException("Proven Meta camera rig missing from scene.");
        var viewer = new GameObject("Physio Fixture Viewer").AddComponent<FixtureViewer>();
        ConfigureMaterials(viewer);
        HandReviewSceneBuilder.Configure(viewer, rig);
        foreach (var root in scene.GetRootGameObjects())
            foreach (var child in root.GetComponentsInChildren<Transform>(true))
                if (GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(child.gameObject) != 0)
                    throw new InvalidOperationException("Missing script on " + child.name);

        Directory.CreateDirectory(Path.GetDirectoryName(ScenePath));
        if (!EditorSceneManager.SaveScene(scene, ScenePath))
            throw new IOException("Could not save fixture scene.");
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
    }

    private static void ConfigureMaterials(FixtureViewer viewer)
    {
        var serialized = new SerializedObject(viewer);
        serialized.FindProperty("bodyMaterial").objectReferenceValue = MaterialAsset(
            "FixtureBody", new Color(.05f, .55f, 1f, .33f), true);
        serialized.FindProperty("boneMaterial").objectReferenceValue = MaterialAsset(
            "FixtureBones", new Color(.3f, .95f, 1f), false);
        serialized.FindProperty("jointMaterial").objectReferenceValue = MaterialAsset(
            "FixtureJoints", Color.white, false);
        serialized.ApplyModifiedPropertiesWithoutUndo();
    }

    private static Material MaterialAsset(string name, Color color, bool transparent)
    {
        const string directory = "Assets/Physio/Materials";
        Directory.CreateDirectory(directory);
        var path = directory + "/" + name + ".mat";
        var existing = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (existing != null) return existing;
        var shader = Shader.Find("Standard");
        if (shader == null) throw new InvalidOperationException("Built-in Standard shader is unavailable.");
        var material = new Material(shader) { name = name, color = color };
        material.SetFloat("_Glossiness", .2f);
        if (transparent)
        {
            material.SetFloat("_Mode", 2);
            material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            material.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            material.SetInt("_ZWrite", 0);
            material.EnableKeyword("_ALPHABLEND_ON");
            material.SetOverrideTag("RenderType", "Transparent");
            material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
        }
        AssetDatabase.CreateAsset(material, path);
        return material;
    }

    private static void ConfigurePlayer()
    {
        PlayerSettings.companyName = "HTH";
        PlayerSettings.productName = "Physio Replay";
        PlayerSettings.bundleVersion = "0.3.2";
        PlayerSettings.SetApplicationIdentifier(UnityEditor.Build.NamedBuildTarget.Android, "com.hth.physio.fixture");
        PlayerSettings.Android.bundleVersionCode = 9;
        PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel32;
        PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevel34;
        PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
        AssetDatabase.SaveAssets();
    }
}
