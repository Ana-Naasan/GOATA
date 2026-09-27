#nullable enable
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Physio.Workflow;
using UnityEngine;

namespace Physio.Viewer
{
    public sealed partial class WorkflowPanel
    {
        private string leafSha256 = "";
        private string connectionStatus = "Service connection not checked";
        private CancellationTokenSource? connectionCancellation;

        private bool LoadConnection()
        {
            try
            {
                var connection = ProcessingConnection.LoadOnce(Application.persistentDataPath);
                if (connection == null) return false;
                endpoint = connection.Endpoint.AbsoluteUri.TrimEnd('/');
                token = connection.BearerToken;
                leafSha256 = connection.LeafSha256;
                connectionStatus = "Checking the processing connection…";
                return true;
            }
            catch (Exception)
            {
                token = leafSha256 = "";
                connectionStatus = "Connection setup failed. Open Options to reconnect.";
                Debug.LogWarning("PHYSIO_CONNECTION_SETUP_FAILED");
                return false;
            }
        }

        private void AddConnectionOptions(List<(string, Action)> items)
        {
            body.text = $"{connectionStatus}\n{(endpoint.Length == 0 ? "No service address" : endpoint)} · {(token.Length == 0 ? "Access token needed" : "Access token ready")}";
            items.Add(("Check processing connection", CheckConnection));
            items.Add(("Service address", () => Keyboard("https://your-service", false, value =>
            {
                var uri = new Uri(value.Trim());
                ProcessingClient.ValidateEndpoint(uri);
                var address = uri.AbsoluteUri.TrimEnd('/');
                if (endpoint != address) token = leafSha256 = "";
                endpoint = address;
                PlayerPrefs.SetString("physio.processing.url", endpoint); PlayerPrefs.Save();
                connectionStatus = "Service connection not checked";
                Show(Screen.Options);
            })));
            items.Add(("Access token", () => Keyboard("Service access token", true, value =>
            {
                ProcessingConnection.ValidateToken(value.Trim()); token = value.Trim();
                connectionStatus = "Service connection not checked"; Show(Screen.Options);
            })));
            items.Add(("Private certificate fingerprint", () => Keyboard("SHA-256 fingerprint (optional)", false, value =>
            {
                leafSha256 = ProcessingConnection.NormalizePin(value);
                connectionStatus = "Service connection not checked"; Show(Screen.Options);
            })));
        }

        private async void CheckConnection()
        {
            if (busy || connectionCancellation != null) return;
            if (string.IsNullOrWhiteSpace(endpoint) || string.IsNullOrWhiteSpace(token))
            {
                connectionStatus = "Processing connection needs setup. Saved recordings are retained.";
                status.text = connectionStatus;
                return;
            }
            var checkedEndpoint = endpoint; var checkedToken = token; var checkedPin = leafSha256;
            bool SameConnection() => endpoint == checkedEndpoint && token == checkedToken && leafSha256 == checkedPin;
            using var cancellation = new CancellationTokenSource();
            connectionCancellation = cancellation;
            connectionStatus = "Checking secure processing connection…";
            status.text = connectionStatus;
            try
            {
                using var client = new ProcessingClient(store, new Uri(checkedEndpoint), checkedToken, leafSha256: checkedPin);
                await Task.Run(() => client.CheckConnectionAsync(cancellation.Token));
                if (this == null || !SameConnection()) return;
                connectionStatus = "Service connected";
                Debug.Log("PHYSIO_CONNECTION_READY: authenticated service reached; inference not tested");
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
            catch (Exception)
            {
                if (SameConnection()) connectionStatus = "Connection unavailable. Keep the laptop connected and retry.";
                Debug.LogWarning("PHYSIO_CONNECTION_CHECK_FAILED");
            }
            finally
            {
                connectionCancellation = null;
                if (this != null)
                {
                    if (screen == Screen.Options) Show(Screen.Options, false);
                    else if (SameConnection() && status.text == "Checking secure processing connection…")
                        status.text = connectionStatus;
                }
            }
        }
    }
}
