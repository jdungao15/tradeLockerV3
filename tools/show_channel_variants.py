"""
Diagnostic tool to show channel ID variants for Telegram channels.
This helps you understand which ID format to use when configuring channels.

Usage:
    python tools/show_channel_variants.py <channel_id>

Example:
    python tools/show_channel_variants.py -1002918525969
    python tools/show_channel_variants.py 2486712356
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.account_channels import AccountChannelManager


def show_variants(channel_id):
    """Show all possible ID variants for a given channel ID."""
    try:
        channel_id = int(channel_id)
    except ValueError:
        print(f"Error: '{channel_id}' is not a valid integer")
        return

    manager = AccountChannelManager()
    variants = manager._get_channel_id_variants(channel_id)

    print(f"\n{'='*60}")
    print(f"Channel ID Variants for: {channel_id}")
    print(f"{'='*60}\n")

    print("All possible ID formats that will match this channel:")
    for i, variant in enumerate(variants, 1):
        is_current = "<- (input ID)" if variant == channel_id else ""
        print(f"  {i}. {variant:>17} {is_current}")

    print("\n" + "="*60)
    print("Note: Any of these IDs can be used in your configuration")
    print("="*60 + "\n")


def show_all_configured():
    """Show all currently configured channels and their variants."""
    manager = AccountChannelManager()
    channels = manager.get_all_monitored_channels()

    if not channels:
        print("\nWarning: No channels currently configured\n")
        return

    print(f"\n{'='*60}")
    print("Currently Configured Channels")
    print(f"{'='*60}\n")

    for ch_id in channels:
        variants = manager._get_channel_id_variants(ch_id)
        print(f"Channel: {ch_id}")
        print(f"  Matches: {len(variants)} variant IDs")
        print(f"  Variants: {', '.join(map(str, variants[:3]))}...")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCurrent Configuration:")
        show_all_configured()
        print("\nUsage: python tools/show_channel_variants.py <channel_id>")
        print("Example: python tools/show_channel_variants.py -1002918525969")
        sys.exit(1)

    channel_id = sys.argv[1]
    show_variants(channel_id)
