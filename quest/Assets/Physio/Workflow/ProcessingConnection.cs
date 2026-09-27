#nullable enable
using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Physio.Replay;
using static Physio.Replay.ReplayJson;

namespace Physio.Workflow
{
    /// <summary>Explicit private-server credentials; never persisted by the application.</summary>
    public sealed class ProcessingConnection
    {
        public const string FileName = "processing-connection.json";
        public const int MaxBytes = 16 * 1024;
        public Uri Endpoint { get; }
        public string BearerToken { get; }
        public string LeafSha256 { get; }

        public ProcessingConnection(Uri endpoint, string bearerToken, string leafSha256 = "")
        {
            ProcessingClient.ValidateEndpoint(endpoint);
            ValidateToken(bearerToken);
            Endpoint = endpoint; BearerToken = bearerToken; LeafSha256 = NormalizePin(leafSha256);
        }

        public static void ValidateToken(string value) => Require(!string.IsNullOrWhiteSpace(value)
            && value.Length <= 4096 && !value.Any(char.IsControl), "Enter a valid deployment token.");

        public static string NormalizePin(string value)
        {
            var pin = value.Trim().ToLowerInvariant();
            Require(pin.Length == 0 || pin.Length == 64 && pin.All(c => c >= '0' && c <= '9' || c >= 'a' && c <= 'f'),
                "Certificate fingerprint must contain exactly 64 SHA-256 hex characters, or be empty for normal HTTPS.");
            return pin;
        }

        public static ProcessingConnection? LoadOnce(string privateDirectory)
        {
            var path = Path.Combine(privateDirectory, FileName);
            if (!File.Exists(path)) return null;
            try
            {
                byte[] bytes;
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None))
                {
                    Require(stream.Length > 0 && stream.Length <= MaxBytes, "Connection file exceeds the supported bound.");
                    bytes = new byte[(int)stream.Length]; var read = 0;
                    while (read < bytes.Length)
                    {
                        var count = stream.Read(bytes, read, bytes.Length - read);
                        Require(count > 0, "Connection file is incomplete."); read += count;
                    }
                    Require(stream.ReadByte() == -1, "Connection file changed while loading.");
                }
                var value = WorkflowJson.Fields(WorkflowJson.Read(bytes), "endpoint bearer_token", "tls_leaf_sha256");
                Require(Uri.TryCreate(ReplayJson.String(value["endpoint"], 2048), UriKind.Absolute, out var endpoint), "Enter a valid HTTPS origin.");
                return new ProcessingConnection(endpoint!, ReplayJson.String(value["bearer_token"], 4096),
                    value["tls_leaf_sha256"] == null ? "" : ReplayJson.String(value["tls_leaf_sha256"], 64));
            }
            finally { File.Delete(path); }
        }

        public static HttpClientHandler CreateHandler(string leafSha256)
        {
            var pin = NormalizePin(leafSha256);
            var handler = new HttpClientHandler { AllowAutoRedirect = false };
            if (pin.Length == 0) return handler;
            handler.ServerCertificateCustomValidationCallback = (_, certificate, chain, errors) =>
            {
                // Only explicit leaf identity can replace private CA trust; host, dates and other chain failures still apply.
                if (certificate == null || (errors & ~SslPolicyErrors.RemoteCertificateChainErrors) != 0) return false;
                var now = DateTime.UtcNow;
                if (now < certificate.NotBefore.ToUniversalTime() || now > certificate.NotAfter.ToUniversalTime()) return false;
                if ((errors & SslPolicyErrors.RemoteCertificateChainErrors) != 0 && (chain == null ||
                    chain.ChainStatus.Length == 0 || chain.ChainStatus.Any(status =>
                        (status.Status & ~(X509ChainStatusFlags.UntrustedRoot | X509ChainStatusFlags.PartialChain)) != 0))) return false;
                using var sha = SHA256.Create();
                var actual = BitConverter.ToString(sha.ComputeHash(certificate.RawData)).Replace("-", "").ToLowerInvariant();
                return string.Equals(actual, pin, StringComparison.Ordinal);
            };
            return handler;
        }
    }
}
