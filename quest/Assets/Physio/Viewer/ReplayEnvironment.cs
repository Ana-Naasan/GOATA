using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace Physio.Viewer
{
    /// <summary>Stationary Moon replay setting; capture always requests passthrough.</summary>
    public sealed class ReplayEnvironment : MonoBehaviour
    {
        [SerializeField] private OVRManager manager;
        [SerializeField] private OVRPassthroughLayer passthrough;
        [SerializeField] private Camera eyeCamera;
        [SerializeField] private Transform head;
        [SerializeField] private Transform trackingSpace;
        [SerializeField] private Texture2D earthTexture;
        [SerializeField] private GameObject platformModel;
        [SerializeField] private GameObject rockModel;
        [SerializeField] private GameObject craterModel;
        [SerializeField] private GameObject dishModel;
        private GameObject room;
        private Transform earth;
        private Transform dish;
        private Material accent;
        private CameraClearFlags originalFlags;
        private Color originalBackground;
        private int passthroughTransition;
        private readonly List<Material> materials = new();
        public bool IsQuietRoom { get; private set; }
        public bool PassthroughReady { get; private set; } = true;
        public bool PassthroughTimedOut { get; private set; }
        public bool IsRoomCollider(Collider collider) => room != null && collider != null &&
            collider.transform.IsChildOf(room.transform);

        public void Configure(OVRManager ovr, OVRPassthroughLayer layer, Camera camera, Transform eye,
            Transform floor, Texture2D earthMap, GameObject platform, GameObject rock, GameObject crater, GameObject satellite)
        {
            manager = ovr; passthrough = layer; eyeCamera = camera; head = eye; trackingSpace = floor;
            earthTexture = earthMap; platformModel = platform; rockModel = rock;
            craterModel = crater; dishModel = satellite;
        }

        private void Start()
        {
            if (manager == null || passthrough == null || eyeCamera == null || head == null || trackingSpace == null ||
                earthTexture == null || platformModel == null || rockModel == null || craterModel == null || dishModel == null)
            {
                Debug.LogError("Moon replay setting is missing a Quest rig or sourced asset.");
                enabled = false; return;
            }
            originalFlags = eyeCamera.clearFlags;
            originalBackground = eyeCamera.backgroundColor;
            passthrough.passthroughLayerResumed.AddListener(OnPassthroughResumed);
            CreateRoom();
            room.SetActive(false);
        }

        public void Toggle() { if (enabled) SetQuietRoom(!IsQuietRoom); }

        public void SetQuietRoom(bool value)
        {
            if (!enabled || manager == null || passthrough == null || room == null || value == IsQuietRoom) return;
            IsQuietRoom = value;
            if (value)
            {
                passthroughTransition++;
                PassthroughReady = false;
                PassthroughTimedOut = false;
                var yaw = Quaternion.Euler(0, head.eulerAngles.y, 0);
                room.transform.SetPositionAndRotation(
                    new Vector3(head.position.x, trackingSpace.position.y, head.position.z), yaw);
                room.SetActive(true);
                eyeCamera.clearFlags = CameraClearFlags.SolidColor;
                eyeCamera.backgroundColor = new Color(.005f, .012f, .027f, 1f);
                passthrough.enabled = false;
                manager.isInsightPassthroughEnabled = false;
            }
            else
            {
                passthroughTransition++;
                PassthroughReady = false;
                PassthroughTimedOut = false;
                manager.isInsightPassthroughEnabled = true;
                passthrough.enabled = true;
                eyeCamera.clearFlags = originalFlags;
                eyeCamera.backgroundColor = originalBackground;
                // Cover a black compositor frame until passthrough actually resumes.
                StartCoroutine(CheckPassthroughResume(passthroughTransition));
            }
        }

        public void RetryPassthrough()
        {
            if (IsQuietRoom || PassthroughReady || manager == null || passthrough == null) return;
            PassthroughTimedOut = false;
            passthroughTransition++;
            StartCoroutine(RestartPassthrough(passthroughTransition));
        }

        private IEnumerator RestartPassthrough(int transition)
        {
            passthrough.enabled = false;
            manager.isInsightPassthroughEnabled = false;
            yield return null;
            if (transition != passthroughTransition || IsQuietRoom) yield break;
            manager.isInsightPassthroughEnabled = true;
            passthrough.enabled = true;
            StartCoroutine(CheckPassthroughResume(transition));
        }

        private IEnumerator CheckPassthroughResume(int transition)
        {
            yield return new WaitForSecondsRealtime(3f);
            if (transition == passthroughTransition && !IsQuietRoom && room != null && room.activeSelf)
            {
                PassthroughTimedOut = true;
                Debug.LogError("PHYSIO_PASSTHROUGH_RESUME_TIMEOUT: capture remains blocked");
            }
        }

        private void OnPassthroughResumed(OVRPassthroughLayer layer)
        {
            if (IsQuietRoom || room == null) return;
            passthroughTransition++;
            PassthroughReady = true;
            PassthroughTimedOut = false;
            room.SetActive(false);
        }

        private void CreateRoom()
        {
            room = new GameObject("Open-air Moon training facility");
            var regolith = MakeMaterial(new Color(.16f, .18f, .22f));
            var metal = MakeMaterial(new Color(.16f, .25f, .32f));
            var darkMetal = MakeMaterial(new Color(.07f, .12f, .18f));
            accent = MakeMaterial(new Color(.12f, .77f, .94f));
            accent.EnableKeyword("_EMISSION");
            accent.SetColor("_EmissionColor", new Color(.03f, .30f, .44f));
            Block("Moon regolith", new Vector3(0, -.18f, 0), new Vector3(70, .26f, 70), regolith);
            for (var x = -3; x <= 3; x += 2)
                for (var z = -3; z <= 3; z += 2)
                    Model(platformModel, "Facility deck tile", new Vector3(x, -.1f, z), Vector3.one, metal);
            // Low barriers preserve the open skyline and receive play-mode splats.
            Block("North training barrier", new Vector3(0, .36f, 4.12f), new Vector3(8.5f, .70f, .12f), darkMetal);
            Block("South training barrier", new Vector3(0, .36f, -4.12f), new Vector3(8.5f, .70f, .12f), darkMetal);
            Block("East training barrier", new Vector3(4.12f, .36f, 0), new Vector3(.12f, .70f, 8.5f), darkMetal);
            Block("West training barrier", new Vector3(-4.12f, .36f, 0), new Vector3(.12f, .70f, 8.5f), darkMetal);
            for (var side = -1; side <= 1; side += 2)
            {
                Block("Animated deck edge", new Vector3(side * 3.96f, .012f, 0), new Vector3(.025f, .012f, 7.8f), accent);
                Block("Animated deck edge", new Vector3(0, .012f, side * 3.96f), new Vector3(7.8f, .012f, .025f), accent);
            }
            var random = new System.Random(17);
            for (var i = 0; i < 16; i++)
            {
                var angle = i * Mathf.PI * 2f / 16f + .23f;
                var radius = 7f + (float)random.NextDouble() * 12f;
                var model = i % 5 == 0 ? craterModel : rockModel;
                var scale = i % 5 == 0 ? 2f : .7f + (float)random.NextDouble() * 1.8f;
                Model(model, "Distant lunar geology", new Vector3(Mathf.Sin(angle) * radius, -.05f,
                    Mathf.Cos(angle) * radius), Vector3.one * scale, regolith);
            }
            dish = Model(dishModel, "Slow scanning dish", new Vector3(-7, -.04f, 9),
                Vector3.one * 2.7f, metal).transform;
            var earthObject = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            earthObject.name = "Earth above lunar horizon - NASA Blue Marble";
            earthObject.transform.SetParent(room.transform, false);
            earthObject.transform.localPosition = new Vector3(4f, 10f, 28f);
            earthObject.transform.localScale = Vector3.one * 4.8f;
            Destroy(earthObject.GetComponent<Collider>());
            var earthMaterial = MakeMaterial(Color.white);
            earthMaterial.mainTexture = earthTexture;
            earthMaterial.EnableKeyword("_EMISSION");
            earthMaterial.SetTexture("_EmissionMap", earthTexture);
            earthMaterial.SetColor("_EmissionColor", Color.white * .44f);
            earthObject.GetComponent<Renderer>().sharedMaterial = earthMaterial;
            earth = earthObject.transform;
            var stars = MakeMaterial(new Color(.75f, .87f, 1f));
            stars.EnableKeyword("_EMISSION");
            stars.SetColor("_EmissionColor", Color.white * .6f);
            for (var i = 0; i < 28; i++)
            {
                var star = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                star.name = "Distant star";
                star.transform.SetParent(room.transform, false);
                star.transform.localPosition = new Vector3((float)random.NextDouble() * 70f - 35f,
                    9f + (float)random.NextDouble() * 28f, 16f + (float)random.NextDouble() * 32f);
                star.transform.localScale = Vector3.one * (.025f + (float)random.NextDouble() * .045f);
                star.GetComponent<Renderer>().sharedMaterial = stars;
                Destroy(star.GetComponent<Collider>());
            }
            var light = new GameObject("Moonlight").AddComponent<Light>();
            light.transform.SetParent(room.transform, false);
            light.transform.localRotation = Quaternion.Euler(45f, -32f, 0);
            light.type = LightType.Directional; light.shadows = LightShadows.None;
            light.color = new Color(.70f, .82f, 1f); light.intensity = 1.35f;
        }

        private void LateUpdate()
        {
            if (!IsQuietRoom || room == null) return;
            if (earth != null) earth.Rotate(Vector3.up, Time.deltaTime * .35f, Space.Self);
            if (dish != null) dish.Rotate(Vector3.up, Time.deltaTime * 4f, Space.World);
            if (accent != null) accent.SetColor("_EmissionColor",
                new Color(.02f, .23f, .34f) * (1f + .18f * Mathf.Sin(Time.unscaledTime * 1.6f)));
        }

        private Material MakeMaterial(Color color)
        {
            var material = new Material(Shader.Find("Standard")) { color = color };
            material.SetFloat("_Glossiness", .18f);
            materials.Add(material);
            return material;
        }

        private GameObject Model(GameObject prefab, string name, Vector3 position, Vector3 scale, Material material)
        {
            var model = Instantiate(prefab, room.transform);
            model.name = name;
            model.transform.localPosition = position; model.transform.localScale = scale;
            foreach (var renderer in model.GetComponentsInChildren<Renderer>()) renderer.sharedMaterial = material;
            return model;
        }

        private void Block(string name, Vector3 position, Vector3 scale, Material material)
        {
            var block = GameObject.CreatePrimitive(PrimitiveType.Cube);
            block.name = name;
            block.transform.SetParent(room.transform, false);
            block.transform.localPosition = position; block.transform.localScale = scale;
            block.GetComponent<Renderer>().sharedMaterial = material;
        }

        private void OnDestroy()
        {
            if (passthrough != null) passthrough.passthroughLayerResumed.RemoveListener(OnPassthroughResumed);
            foreach (var material in materials) if (material != null) Destroy(material);
            if (room != null) Destroy(room);
        }
    }
}
