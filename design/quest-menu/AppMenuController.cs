using System;
using System.Collections.Generic;
using UnityEngine;

namespace FootAssessment.Quest
{
    public enum AppScreen
    {
        Home,
        Patients,
        History,
        Capture,
        Review,
        Options
    }

    [Serializable]
    public sealed class ScreenBinding
    {
        [SerializeField] private AppScreen screen;
        [SerializeField] private GameObject screenRoot;
        [SerializeField] private GameObject menuSelectedMark;

        public AppScreen Screen => screen;
        public GameObject Root => screenRoot;
        public GameObject SelectedMark => menuSelectedMark;
    }

    /// <summary>
    /// App-owned navigation for an existing Unity Quest scene. This does not
    /// create Quest system UI, UI Set prefabs, patient data, or capture services.
    /// Put this component on a persistent object outside all screen roots.
    /// </summary>
    public sealed class AppMenuController : MonoBehaviour
    {
        [SerializeField] private GameObject menuRoot;
        [SerializeField] private ScreenBinding[] screens = new ScreenBinding[0];
        [SerializeField] private AppScreen initialScreen = AppScreen.Home;

        private bool ready;
        private bool menuOpen;
        private AppScreen currentScreen;
        private AppScreen returnFromOptions = AppScreen.Home;

        public AppScreen CurrentScreen => currentScreen;
        public bool IsMenuOpen => menuOpen;

        public event Action<AppScreen> ScreenChanged;
        public event Action<bool> MenuVisibilityChanged;

        private void Start()
        {
            if (!ValidateBindings())
            {
                enabled = false;
                return;
            }

            foreach (ScreenBinding binding in screens)
            {
                binding.Root.SetActive(false);
                if (binding.SelectedMark != null)
                    binding.SelectedMark.SetActive(false);
            }

            menuRoot.SetActive(false);
            ready = true;

            if (!TryOpen(initialScreen))
                enabled = false;
        }

        public bool TryOpen(AppScreen destination)
        {
            if (!ready)
            {
                Debug.LogError("Foot Assessment menu has not been initialized.", this);
                return false;
            }

            ScreenBinding selected = Find(destination);
            if (selected == null)
            {
                Debug.LogError("Foot Assessment screen is not connected: " + destination, this);
                return false;
            }

            if (destination == AppScreen.Options && currentScreen != AppScreen.Options)
                returnFromOptions = currentScreen;

            foreach (ScreenBinding binding in screens)
            {
                bool active = binding == selected;
                binding.Root.SetActive(active);
                if (binding.SelectedMark != null)
                    binding.SelectedMark.SetActive(active);
            }

            currentScreen = destination;
            SetMenuOpen(false);
            ScreenChanged?.Invoke(destination);
            return true;
        }

        // Bind these methods to the app's UI Set button/poke/ray select events.
        public void OpenHome() => TryOpen(AppScreen.Home);
        public void OpenPatients() => TryOpen(AppScreen.Patients);
        public void OpenHistory() => TryOpen(AppScreen.History);
        public void OpenCapture() => TryOpen(AppScreen.Capture);
        public void OpenReview() => TryOpen(AppScreen.Review);
        public void OpenOptions() => TryOpen(AppScreen.Options);

        public void ToggleMenu() => SetMenuOpen(!menuOpen);
        public void CloseMenu() => SetMenuOpen(false);

        public void Back()
        {
            if (menuOpen)
            {
                CloseMenu();
                return;
            }

            switch (currentScreen)
            {
                case AppScreen.Review:
                    OpenCapture();
                    break;
                case AppScreen.Capture:
                    OpenHistory();
                    break;
                case AppScreen.History:
                    OpenPatients();
                    break;
                case AppScreen.Patients:
                    OpenHome();
                    break;
                case AppScreen.Options:
                    TryOpen(returnFromOptions);
                    break;
                default:
                    CloseMenu();
                    break;
            }
        }

        private void SetMenuOpen(bool visible)
        {
            if (!ready)
            {
                Debug.LogError("Foot Assessment menu has not been initialized.", this);
                return;
            }

            if (menuOpen == visible)
                return;

            menuOpen = visible;
            menuRoot.SetActive(visible);
            MenuVisibilityChanged?.Invoke(visible);
        }

        private ScreenBinding Find(AppScreen screen)
        {
            foreach (ScreenBinding binding in screens)
            {
                if (binding.Screen == screen)
                    return binding;
            }

            return null;
        }

        private bool ValidateBindings()
        {
            if (menuRoot == null || screens == null || screens.Length == 0)
            {
                Debug.LogError("Assign a menu root and at least one screen binding.", this);
                return false;
            }

            if (menuRoot == gameObject || transform.IsChildOf(menuRoot.transform))
            {
                Debug.LogError("Keep the menu controller outside the menu root.", this);
                return false;
            }

            var ids = new HashSet<AppScreen>();
            var roots = new HashSet<GameObject>();
            var marks = new HashSet<GameObject>();
            var checkedRoots = new List<GameObject>();
            var checkedMarks = new List<GameObject>();
            bool hasInitialScreen = false;

            foreach (ScreenBinding binding in screens)
            {
                if (binding == null || binding.Root == null)
                {
                    Debug.LogError("Every listed screen needs a root GameObject.", this);
                    return false;
                }

                if (!ids.Add(binding.Screen) || !roots.Add(binding.Root))
                {
                    Debug.LogError("Screen IDs and screen roots must be unique.", this);
                    return false;
                }

                if (binding.Root == menuRoot || binding.Root == gameObject ||
                    transform.IsChildOf(binding.Root.transform) ||
                    menuRoot.transform.IsChildOf(binding.Root.transform) ||
                    binding.Root.transform.IsChildOf(menuRoot.transform))
                {
                    Debug.LogError("Keep the controller and menu outside screen roots.", this);
                    return false;
                }

                foreach (GameObject otherRoot in checkedRoots)
                {
                    if (binding.Root.transform.IsChildOf(otherRoot.transform) ||
                        otherRoot.transform.IsChildOf(binding.Root.transform))
                    {
                        Debug.LogError("Screen roots must not be nested inside each other.", this);
                        return false;
                    }
                }
                checkedRoots.Add(binding.Root);

                if (binding.SelectedMark != null &&
                    (binding.SelectedMark == menuRoot ||
                     !binding.SelectedMark.transform.IsChildOf(menuRoot.transform) ||
                     !marks.Add(binding.SelectedMark)))
                {
                    Debug.LogError("Each selection mark must be a distinct child of the menu root.", this);
                    return false;
                }

                if (binding.SelectedMark != null)
                {
                    foreach (GameObject otherMark in checkedMarks)
                    {
                        if (binding.SelectedMark.transform.IsChildOf(otherMark.transform) ||
                            otherMark.transform.IsChildOf(binding.SelectedMark.transform))
                        {
                            Debug.LogError("Selection marks must not be nested inside each other.", this);
                            return false;
                        }
                    }
                    checkedMarks.Add(binding.SelectedMark);
                }

                if (binding.Screen == initialScreen)
                    hasInitialScreen = true;
            }

            if (!hasInitialScreen)
                Debug.LogError("The initial screen needs a screen binding.", this);

            return hasInitialScreen;
        }
    }
}