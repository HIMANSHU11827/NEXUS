from typing import Optional

from providers.oauth.providers.autoregister import register_all_oauth_providers
from providers.oauth.registry import get_oauth_provider, get_oauth_providers
from providers.oauth.storage import load_oauth_token_store
from providers.oauth.types import OAuthAuthInfo, OAuthLoginCallbacks, OAuthPrompt
from providers.profiles import ProviderProfile, load_profile_store


def init_auth_cli(subparsers) -> None:
    register_all_oauth_providers()

    auth_parser = subparsers.add_parser("auth", help="Manage provider authentication & profiles")
    auth_sub = auth_parser.add_subparsers(dest="auth_command")

    login_parser = auth_sub.add_parser("login", help="Login to an OAuth provider")
    login_parser.add_argument("provider", type=str, help="Provider ID to login to")
    login_parser.add_argument("--name", type=str, default="default", help="Profile name for this login")
    login_parser.add_argument("--port", type=int, help="Callback server port override")
    login_parser.add_argument("--host", type=str, default="127.0.0.1", help="Callback server host")

    logout_parser = auth_sub.add_parser("logout", help="Remove stored credentials for a provider")
    logout_parser.add_argument("provider", type=str, help="Provider ID to logout from")
    logout_parser.add_argument("--name", type=str, help="Profile name (defaults to default)")

    add_key_parser = auth_sub.add_parser("add-key", help="Add an API key profile for a provider")
    add_key_parser.add_argument("provider", type=str, help="Provider ID")
    add_key_parser.add_argument("--key", type=str, required=True, help="API key")
    add_key_parser.add_argument("--name", type=str, default="default", help="Profile name")
    add_key_parser.add_argument("--email", type=str, help="Optional email/identifier")

    list_parser = auth_sub.add_parser("list", help="List all providers and profiles")
    list_parser.add_argument("provider", type=str, nargs="?", help="Filter by provider")

    default_parser = auth_sub.add_parser("set-default", help="Set default profile for a provider")
    default_parser.add_argument("provider", type=str, help="Provider ID")
    default_parser.add_argument("name", type=str, help="Profile name to set as default")

    delete_parser = auth_sub.add_parser("delete-profile", help="Delete a profile")
    delete_parser.add_argument("provider", type=str, help="Provider ID")
    delete_parser.add_argument("name", type=str, help="Profile name to delete")

    detect_parser = auth_sub.add_parser("auto-detect", help="Auto-detect available providers & regenerate task routing")
    detect_parser.add_argument("--force", action="store_true", help="Regenerate even if task_routing_auto.yml exists")

    strategy_parser = auth_sub.add_parser("strategy", help="Set credential rotation strategy for a provider")
    strategy_parser.add_argument("provider", type=str, help="Provider ID")
    strategy_parser.add_argument("strategy", type=str, choices=["fill_first", "round_robin", "random"], help="Rotation strategy")

    return auth_parser


async def handle_auth_login(args) -> None:
    register_all_oauth_providers()
    provider = get_oauth_provider(args.provider)
    if not provider:
        print(f"Unknown OAuth provider: {args.provider}")
        print(f"Available: {[p.id for p in get_oauth_providers()]}")
        return

    store = load_oauth_token_store()
    callbacks = _make_cli_callbacks()
    try:
        credentials = await provider.login(callbacks)
        store.set(args.provider, credentials)
        profile_store = load_profile_store()
        profile_store.add_profile(ProviderProfile(
            name=args.name,
            provider=args.provider,
            type="oauth",
            access=credentials.access,
            refresh=credentials.refresh,
            expires=credentials.expires,
            email=getattr(credentials, "email", None),
        ))
        print(f"\nLogged in as profile '{args.name}' for {provider.name}")
        email = getattr(credentials, "email", None)
        if email:
            print(f"Account: {email}")
    except RuntimeError as e:
        print(f"\nLogin failed: {e}")
    except Exception as e:
        # Network errors (httpx/httpcore connection failures, timeouts) and any
        # unexpected provider error must surface as a clean message, never as an
        # unhandled traceback to the shell.
        print(f"\nLogin failed: {type(e).__name__}: {e}")
        print("Check the provider credentials, network access, and that any"
              " required OAuth client_id is configured.")
    except KeyboardInterrupt:
        print("\nLogin cancelled")


async def handle_auth_logout(args) -> None:
    store = load_oauth_token_store()
    if args.name:
        profile_store = load_profile_store()
        if profile_store.delete_profile(args.provider, args.name):
            print(f"Deleted profile '{args.name}' for {args.provider}")
        else:
            print(f"No profile '{args.name}' for {args.provider}")
    else:
        if store.delete(args.provider):
            print(f"Logged out from {args.provider}")
        else:
            print(f"No stored credentials for {args.provider}")


def handle_auth_add_key(args) -> None:
    profile_store = load_profile_store()
    profile = ProviderProfile(
        name=args.name,
        provider=args.provider,
        type="api_key",
        api_key=args.key,
        email=args.email,
    )
    profile_store.add_profile(profile)
    print(f"Added API key profile '{args.name}' for {args.provider}")


def handle_auth_list(args) -> None:
    register_all_oauth_providers()
    oauth_providers = get_oauth_providers()
    store = load_oauth_token_store()
    profile_store = load_profile_store()

    if args.provider:
        _print_provider_profiles(args.provider, oauth_providers, store, profile_store)
        return

    all_providers = sorted(set(
        list(profile_store.providers()) +
        [p.id for p in oauth_providers]
    ))
    print("Provider Profiles:")
    for pid in all_providers:
        _print_provider_profiles(pid, oauth_providers, store, profile_store)


def _print_provider_profiles(pid: str, oauth_providers, store, profile_store) -> None:
    oauth_match = next((p for p in oauth_providers if p.id == pid), None)
    name = oauth_match.name if oauth_match else pid
    profiles = profile_store.list_profiles(pid)
    oauth_creds = store.get(pid)
    print(f"\n{pid} ({name})")
    if oauth_creds:
        import time
        rem = max(0, oauth_creds.expires - time.time() * 1000) // 1000
        print(f"  [OAuth session: expires in {rem}s]")
    if profiles:
        for p in profiles:
            marker = ">" if profile_store._defaults.get(pid) == p.name else " "
            key_type = "oauth" if p.type == "oauth" else "api_key"
            email = f" ({p.email})" if p.email else ""
            print(f"  {marker} {p.name:15s} {key_type}{email}")


def handle_auth_set_default(args) -> None:
    profile_store = load_profile_store()
    if profile_store.set_default(args.provider, args.name):
        print(f"Default for {args.provider} set to '{args.name}'")
    else:
        print(f"Profile '{args.name}' not found for {args.provider}")


def handle_auth_delete_profile(args) -> None:
    profile_store = load_profile_store()
    if profile_store.delete_profile(args.provider, args.name):
        print(f"Deleted profile '{args.name}' for {args.provider}")
    else:
        print(f"Profile '{args.name}' not found for {args.provider}")


async def handle_auth_status(args) -> None:
    register_all_oauth_providers()
    store = load_oauth_token_store()
    oauth_providers = get_oauth_providers()

    print("OAuth Login Status:")
    for p in oauth_providers:
        creds = store.get(p.id)
        if creds:
            import time
            remaining = max(0, creds.expires - time.time() * 1000) / 1000
            print(f"  * {p.id:20s} logged in (expires in {remaining:.0f}s)")
        else:
            print(f"    {p.id:20s} not logged in")


def _make_cli_callbacks() -> OAuthLoginCallbacks:
    class CLICallbacks:
        def on_auth(self, *args) -> None:
            if len(args) == 1 and isinstance(args[0], OAuthAuthInfo):
                url = args[0].url
                instructions = args[0].instructions
            else:
                url = str(args[0]) if args else ""
                instructions = str(args[1]) if len(args) > 1 else None
            print(f"\nOpen this URL in your browser:\n{url}")
            if instructions:
                print(f"\n{instructions}")

        async def on_prompt(self, prompt) -> str:
            if isinstance(prompt, OAuthPrompt):
                prompt_text = prompt.message
                if prompt.placeholder:
                    prompt_text += f"\n(default: {prompt.placeholder})"
            else:
                prompt_text = str(prompt)
            result = input(f"\n{prompt_text}\n> ")
            return result.strip()

        def on_progress(self, message: str) -> None:
            print(f"[{message}]")

        async def on_manual_code_input(self) -> Optional[str]:
            result = input("\nPaste the redirect URL or code here (or press Enter if browser completed it):\n> ")
            return result.strip() or None

        async def on_select(self, prompt) -> Optional[str]:
            print(f"\n{prompt.message}")
            for i, opt in enumerate(prompt.options):
                print(f"  {i + 1}. {opt.label}")
            choice = input("> ").strip()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(prompt.options):
                    return prompt.options[idx].id
            except ValueError:
                pass
            return None

        @property
        def signal(self):
            return None

    return CLICallbacks()


def handle_auth_strategy(args) -> None:
    from providers.profiles import load_profile_store
    store = load_profile_store()
    store.set_strategy(args.provider, args.strategy)
    print(f"Strategy for {args.provider} set to '{args.strategy}'")


def handle_auth_auto_detect(args) -> None:
    from providers.auto_detect import run_auto_detect
    run_auto_detect(force=args.force)
