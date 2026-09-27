using UnityEngine;

namespace Physio.Viewer
{
    public sealed class TomatoProjectile : MonoBehaviour
    {
        private FixtureViewer viewer;
        private Texture2D splatTexture;
        private bool hit;

        public void Configure(FixtureViewer owner, Texture2D texture)
        {
            viewer = owner; splatTexture = texture;
        }

        private void OnCollisionEnter(Collision collision)
        {
            if (hit || viewer == null || collision.collider == null) return;
            if (viewer.GetComponent<ReplayPlayInteractions>()?.IsPlayMode != true)
            { Destroy(gameObject); return; }
            var bodyHit = viewer.IsReplayCollider(collision.collider);
            var roomHit = viewer.GetComponent<ReplayEnvironment>()?.IsRoomCollider(collision.collider) == true;
            if (!bodyHit && !roomHit) return;
            var contact = collision.GetContact(0);
            var point = contact.point;
            var normal = contact.normal;
            if (bodyHit && !viewer.TryReplaySurfacePoint(point, out point, out normal)) return;
            hit = true;
            if (bodyHit) viewer.TriggerPlayNudge(GetComponent<Rigidbody>().linearVelocity);
            if (splatTexture != null)
            {
                var splat = GameObject.CreatePrimitive(PrimitiveType.Quad);
                splat.name = "Temporary tomato splat";
                Destroy(splat.GetComponent<Collider>());
                splat.transform.SetParent(bodyHit ? viewer.ReplayRoot : collision.collider.transform, true);
                splat.transform.SetPositionAndRotation(point + normal * .012f,
                    Quaternion.LookRotation(normal));
                splat.transform.localScale = Vector3.one * .23f;
                var material = new Material(Shader.Find("Standard"));
                material.SetFloat("_Mode", 2);
                material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
                material.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
                material.SetInt("_ZWrite", 0);
                material.EnableKeyword("_ALPHABLEND_ON");
                material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
                material.mainTexture = splatTexture;
                material.color = new Color(1f, .12f, .08f, .95f);
                splat.GetComponent<Renderer>().sharedMaterial = material;
                viewer.GetComponent<ReplayPlayInteractions>()?.RegisterSplat(splat);
                Destroy(splat, 1.8f);
                Destroy(material, 1.8f);
            }
            Destroy(gameObject);
        }
    }
}
