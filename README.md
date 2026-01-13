# Wakeup Music AppDaemon App

AppDaemon app that automatically plays music at scheduled wakeup times in Home Assistant.

## Features

- **Smart Scheduling**: Per-day wakeup schedules with flexible time configuration
- **Calendar Integration**: Respects calendar exceptions to skip wakeup music on special days
- **Efficient Performance**: Only active during scheduled wakeup windows
- Plays music on multiple media players simultaneously
- Gradual volume ramping (fade-in) for gentle wakeup
- Comprehensive error handling and logging
- Supports multiple music sources: Spotify, YouTube Music, URLs, and local library
- **Music Assistant Integration**: Full support for [Music Assistant](https://www.music-assistant.io/) for authenticated music service playback, unified library management, and advanced playback features

## Installation

1. Copy `i1_wakeup_music.py` to your AppDaemon apps directory (typically `/config/appdaemon/apps/`)

2. Add configuration to `apps.yaml` in the same directory (see Configuration section below)

3. Restart AppDaemon

## Configuration

Edit `apps.yaml` to configure the app:

```yaml
i1_wakeup_music:
  module: i1_wakeup_music
  class: WakeupMusic
  calendar: "calendar.school_holidays"  # optional
  media_players:
    - media_player.bedroom_speaker
  music_source: "spotify:playlist:YOUR_PLAYLIST_ID"
  initial_volume: 0.1
  target_volume: 0.5
  ramp_duration: 300
  ramp_steps: 10
  days:
    monday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    tuesday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    # ... configure other days
```

### Configuration Parameters

#### Required Parameters

- **days** (dict): Daily schedule configuration with per-day settings
  - Each day (monday, tuesday, etc.) supports:
    - `active` (boolean): Enable/disable for this day
    - `start` (string): Start time for music playback (HH:MM format)
    - `turnoff` (string, optional): Time to stop music (HH:MM format). If not specified, uses `play_duration` parameter

- **media_players** (list): List of media player entity IDs to play music on
  - Examples: `media_player.bedroom_speaker`, `media_player.living_room_speaker`
  - Can be a single string or list of strings

- **music_source** (string): Music source/playlist to play
  - Format depends on media player type
  - **Spotify (standard format):** `spotify:playlist:37i9dQZF1DXcBWIGoYBM5M` (does NOT work with authenticated accounts)
  - **Spotify (Music Assistant - URI format):** `spotify://playlist/37i9dQZF1DX7cZxYLqLUJl`, `spotify://album/ALBUM_ID`, `spotify://artist/ARTIST_ID`, `spotify://track/TRACK_ID` (note: uses slashes `/`, not colons `:`)
  - **Spotify URLs (Music Assistant):** `https://open.spotify.com/playlist/...`, `https://open.spotify.com/album/...`, `https://open.spotify.com/track/...` (converted to URI format internally)
  - **Library URIs (Music Assistant):** `library://artist/1`, `library://album/20`, `library://track/123`, `library://playlist/456` (direct access to Music Assistant's unified library)
  - **YouTube Music (full URL):** `https://music.youtube.com/playlist?list=PLAYLIST_ID`
  - **YouTube Music (full URL):** `https://music.youtube.com/watch?v=VIDEO_ID`
  - **YouTube Music (full URL):** `https://music.youtube.com/album/ALBUM_ID`
  - **YouTube Music (simplified):** `youtube_music:playlist:PLAYLIST_ID`
  - **YouTube Music (simplified):** `youtube_music:track:VIDEO_ID`
  - **YouTube Music (simplified):** `youtube_music:album:ALBUM_ID`
  - **URL:** `http://stream.example.com/music.mp3`
  - **Local library:** `library://music/playlist.m3u`
  - **Note for YouTube Music:** For authenticated playback (to avoid advertisements), configure authentication in your YouTube Music integration (ytube_music_player or Music Assistant). See Authentication Setup section in Troubleshooting for details.
  - **Note for Spotify:** For authenticated/premium Spotify playback, use Music Assistant integration. Standard `spotify:playlist:` format does NOT work with authenticated accounts. Use Music Assistant URI format: `spotify://playlist/ID` (with slashes) or Spotify URLs.

#### Optional Parameters

- **calendar** (string, optional): Calendar entity for exceptions. Set to null/None if no calendar exceptions needed. Calendar is checked once daily at 03:30 AM
- **initial_volume** (float, default: 0.1): Starting volume when music begins (0.0 to 1.0)
- **target_volume** (float, default: 0.5): Final volume after ramping completes (0.0 to 1.0)
- **ramp_duration** (int, default: 300): Duration of volume ramp in seconds
- **ramp_steps** (int, default: 10): Number of steps in volume ramp (more steps = smoother ramp)
- **play_duration** (int, default: 1500): Duration to continue playing after ramp completes (in seconds, 0 = play until manually stopped). Only used if `turnoff` time is not specified in day configuration

#### Music Assistant Parameters

These parameters enable [Music Assistant](https://www.music-assistant.io/) integration for authenticated music service playback and advanced features. Music Assistant is a music library manager that connects your streaming services and local files to a wide range of players.

- **use_music_assistant** (boolean, optional): Force Music Assistant usage. If not specified, auto-detected based on player entity IDs. Music Assistant players are detected by:
  - Entity ID patterns: `media_player.mass_*`, `media_player.ma_*`, or entities ending with `_mass` or `_ma`
  - Platform attribute: Entities with `platform: "music_assistant"` attribute
- **music_assistant_config_entry_id** (string, optional): Music Assistant instance ID for multi-instance setups. Only needed if you have multiple Music Assistant instances configured
- **enqueue** (string, default: "replace"): How new media interacts with the queue. Options:
  - `play`: Play immediately
  - `replace`: Replace entire queue and play (default)
  - `next`: Add after current track
  - `replace_next`: Replace everything after current track
  - `add`: Add to end of queue
- **radio_mode** (boolean, default: false): Enable radio mode to auto-generate a playlist based on the selection. Only available with certain music providers (e.g., Spotify)
- **media_type** (string, optional): Type of content to play. Options: `artist`, `album`, `track`, `playlist`, `radio`. Auto-determined if omitted

**Music Assistant Benefits:**
- **Authenticated Access**: Full access to premium music services (Spotify, Tidal, Qobuz, etc.) without ads
- **Unified Library**: Seamlessly merge local and cloud libraries with automatic track linking
- **Advanced Playback**: Gapless playback, crossfade, and volume normalization for all players
- **Player Flexibility**: Play on almost any device (Sonos, Google Cast, AirPlay, DLNA, etc.) regardless of native service support
- **Smart Search**: Search across all your music sources simultaneously
- **Queue Management**: Advanced queue control and transfer between players
- **Library URIs**: Direct access to Music Assistant's unified library (`library://artist/1`, `library://album/20`, `library://track/123`)

**Music Assistant Setup:**

Music Assistant consists of two components:

1. **Music Assistant Server**: The core application that manages your music library
   - Install as Home Assistant add-on (recommended): Settings > Add-ons > Add-on Store > Music Assistant
   - Or install as Docker container: See [Music Assistant installation documentation](https://www.music-assistant.io/server-install-and-configure/installation/)
   - Access the Music Assistant web interface to configure providers and players

2. **Home Assistant Integration**: Connects Home Assistant to Music Assistant Server
   - Install via HACS (Home Assistant Community Store)
   - The integration automatically installs and manages the add-on if needed
   - Configure in Home Assistant: Settings > Devices & Services > Add Integration > Music Assistant
   - Players will be exposed as `media_player` entities in Home Assistant

3. **Configure Music Providers**: Set up your music sources in Music Assistant
   - Access Music Assistant UI (via Home Assistant or directly)
   - Go to Settings > Music Providers
   - Add and authenticate providers (Spotify, YouTube Music, Tidal, etc.)
   - See [Music Assistant provider documentation](https://www.music-assistant.io/music-providers/) for specific setup instructions

4. **Configure Player Providers**: Set up your audio players
   - Go to Settings > Player Providers in Music Assistant
   - Add player providers (Sonos, Google Cast, AirPlay, DLNA, etc.)
   - Players will automatically appear as `media_player` entities in Home Assistant
   - Entity IDs typically follow patterns like `media_player.mass_*` or `media_player.ma_*`, but may vary

For detailed setup instructions, see the [Music Assistant documentation](https://www.music-assistant.io/).

## How It Works

1. The app checks today's schedule and current time on initialization and daily at 03:30 AM
2. Calendar exceptions are checked once daily at 03:30 AM and cached
3. If current time is before the scheduled start time, music playback is scheduled for the start time
4. If current time is at or after the scheduled start time, music playback starts immediately
5. Music starts at `initial_volume` on all configured media players
6. Volume gradually increases to `target_volume` over `ramp_duration` seconds
7. Music stops at the scheduled `turnoff` time (if specified) or after `play_duration` seconds
8. The app prevents multiple simultaneous wakeup music sessions

## Troubleshooting

### Music doesn't play

1. Check AppDaemon logs for error messages
2. Verify the current day is marked as `active: true` in the `days` configuration
3. Verify the current time is at or after the scheduled `start` time
4. Check calendar exceptions (if configured) - music won't play if calendar exception is active
5. Verify media player entities exist in Home Assistant
6. Check that `music_source` is in correct format for your media player
7. Verify media players support `play_media` and `volume_set` services

### Music doesn't play with Music Assistant

1. **Verify Music Assistant Server is running**
   - Check Home Assistant: Settings > Add-ons > Music Assistant (should show "Running")
   - Or check Docker container if installed separately
   - Access Music Assistant web UI to verify it's accessible

2. **Verify Home Assistant Integration is configured**
   - Check Settings > Devices & Services > Music Assistant
   - Integration should show as "Connected"
   - If not connected, check integration logs for connection errors

3. **Verify player entities exist**
   - Music Assistant players appear as `media_player` entities in Home Assistant
   - Entity IDs may follow patterns like `media_player.mass_*`, `media_player.ma_*`, or end with `_mass`/`_ma`
   - Check entity attributes: `platform` should be `"music_assistant"`
   - Verify players are configured in Music Assistant: Settings > Player Providers

4. **Verify music providers are configured**
   - Access Music Assistant UI
   - Check Settings > Music Providers
   - Ensure providers (Spotify, etc.) are added and authenticated
   - Test playback directly in Music Assistant UI to verify provider works

5. **Check media source format**
   - For Music Assistant, use URI format: `spotify://playlist/ID` (not `spotify:playlist:ID`)
   - Or use Spotify URLs: `https://open.spotify.com/playlist/...`
   - Library URIs: `library://artist/1`, `library://album/20`, `library://track/123`
   - Track names work with Music Assistant (MA will search)

6. **Check AppDaemon logs**
   - Look for `[WEBSOCKET]` and `[MASS]` log entries showing the service call
   - Check for `NotImplementedError` or authentication errors
   - Verify the websocket payload being sent matches expected format

7. **Verify configuration**
   - If player detection isn't working, explicitly set `use_music_assistant: true`
   - Check `music_assistant_config_entry_id` if you have multiple MA instances
   - Verify `enqueue` parameter is set correctly

For more troubleshooting, see [Music Assistant troubleshooting documentation](https://www.music-assistant.io/usage/troubleshooting/).

### Spotify doesn't play (authenticated accounts)

For authenticated Spotify playback (Premium accounts), Music Assistant is required:

1. **Use Music Assistant integration**
   - Standard `spotify:playlist:` format does not work with authenticated accounts
   - Music Assistant provides authenticated access to Spotify Premium features

2. **Verify Spotify provider is configured**
   - Access Music Assistant UI
   - Go to Settings > Music Providers > Spotify
   - Ensure Spotify is added and authenticated
   - Test playback in Music Assistant UI to verify authentication works

3. **Use correct media source format**
   - **URI format (recommended)**: `spotify://playlist/PLAYLIST_ID` (note: slashes, not colons)
   - **URL format**: `https://open.spotify.com/playlist/PLAYLIST_ID`
   - **Track name**: Just the track name (Music Assistant will search)
   - Do NOT use: `spotify:playlist:ID` (standard format doesn't work with authenticated accounts)

4. **Ensure players are Music Assistant players**
   - Players must be exposed through Music Assistant
   - Check entity `platform` attribute is `"music_assistant"`
   - Entity IDs may vary: `media_player.mass_*`, `media_player.ma_*`, or other patterns

5. **Check AppDaemon logs**
   - Look for `[WEBSOCKET]` logs showing the `music_assistant/play_media` service call
   - Check for authentication errors or `NotImplementedError`
   - Verify the websocket payload includes correct `media_id` in URI format

For Spotify provider setup, see [Music Assistant Spotify documentation](https://www.music-assistant.io/music-providers/spotify/).

### YouTube Music doesn't play

1. Ensure your media player supports YouTube Music (e.g., via ytube_music_player or Music Assistant integrations)
2. Verify the YouTube Music integration is properly configured and authenticated in Home Assistant (see Authentication Setup section)
3. Check that the YouTube Music URL format is correct (see Configuration Parameters section)
4. Verify the playlist/album/track exists and is accessible
5. Check AppDaemon logs for YouTube Music-specific error messages

### YouTube Music Authentication Setup

For authenticated YouTube Music playback (to avoid advertisements), you need to configure authentication in the Home Assistant integration. Authentication is handled at the integration level, not in this app's configuration.

#### Using ytube_music_player Integration

1. Install the ytube_music_player integration via HACS (Home Assistant Community Store)
2. Add the integration in Home Assistant (Settings > Devices & Services > Add Integration)
3. Obtain OAuth credentials from Google Cloud Console (follow the integration's documentation)
4. Configure the integration with your OAuth credentials during setup
5. Specify your default output player entity_id during configuration

For detailed setup instructions, refer to the [ytube_music_player GitHub repository](https://github.com/KoljaWindeler/ytube_music_player).

#### Using Music Assistant Integration

1. Install Music Assistant add-on in Home Assistant (Settings > Add-ons > Add-on Store)
2. Install the YT Music PO Token Generator add-on
3. Access Music Assistant UI and create an administrator account
4. Obtain YouTube Music authentication cookies:
   - Log in to YouTube Music in an incognito browser window
   - Use browser developer tools to extract authentication cookies
   - Copy the Cookie value from request headers
5. Configure YouTube Music provider in Music Assistant:
   - Go to Settings > Music Providers > Add new > YouTube Music
   - Enter your Gmail/brand account username
   - Paste the login cookie value
   - Configure PO Token Server URL (default if add-on is on same host)
   - Save configuration

For detailed setup instructions, refer to the [Music Assistant YouTube Music Provider documentation](https://www.music-assistant.io/music-providers/youtube-music/).

**Note:** Authentication cookies may expire over time and require renewal. Free YouTube Music accounts are not supported by Music Assistant.

#### Authentication Troubleshooting

If you encounter authentication errors:

1. Verify the integration is properly configured and authenticated in Home Assistant
2. Check integration logs for authentication errors
3. For Music Assistant: Verify cookies are current and correctly formatted
4. For ytube_music_player: Verify OAuth credentials are valid and not expired
5. Check AppDaemon logs for authentication error messages (they will reference this troubleshooting section)
6. Ensure you have YouTube Music Premium or a valid authenticated account (required for Music Assistant)

### Volume ramping doesn't work

1. Check that `ramp_duration` and `ramp_steps` are configured correctly
2. Verify media players support `volume_set` service
3. Check AppDaemon logs for volume setting errors

### Wrong timing

- Verify time format is HH:MM (e.g., "6:20" not "06:20:00")
- Check day names are lowercase (monday, tuesday, etc.)
- Ensure `active` is set to `true` for desired days
- Check that current time is within the scheduled window

### Multiple triggers

The app includes protection against multiple simultaneous triggers. If music is already playing, new triggers are ignored until the current session completes.

## Logging

The app uses structured logging with appropriate levels:

- **INFO**: Initialization, successful operations, important state changes
- **DEBUG**: Detailed state change information
- **WARNING**: Non-critical issues (e.g., entity validation warnings)
- **ERROR**: Errors with full traceback including line numbers

All error logs include line numbers for easier debugging.

## Example Use Cases

### Single Speaker, Weekday Schedule

```yaml
i1_wakeup_music:
  module: i1_wakeup_music
  class: WakeupMusic
  media_players:
    - media_player.bedroom_speaker
  music_source: "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
  initial_volume: 0.05
  target_volume: 0.4
  ramp_duration: 600
  days:
    monday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    tuesday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    wednesday:
      active: true
      start: "6:30"
      turnoff: "7:00"
    thursday:
      active: true
      start: "6:30"
      turnoff: "7:00"
    friday:
      active: true
      start: "6:30"
      turnoff: "7:00"
    saturday:
      active: false
    sunday:
      active: false
```

### Multiple Speakers, Different Times

```yaml
i1_wakeup_music:
  module: i1_wakeup_music
  class: WakeupMusic
  media_players:
    - media_player.bedroom_speaker
    - media_player.living_room_speaker
    - media_player.kitchen_speaker
  music_source: "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
  initial_volume: 0.1
  target_volume: 0.6
  ramp_duration: 300
  ramp_steps: 15
  days:
    monday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    tuesday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    # ... configure other days
```

### YouTube Music Playlist

```yaml
i1_wakeup_music:
  module: i1_wakeup_music
  class: WakeupMusic
  media_players:
    - media_player.bedroom_speaker
  music_source: "https://music.youtube.com/playlist?list=PLAYLIST_ID"
  initial_volume: 0.1
  target_volume: 0.5
  ramp_duration: 300
  days:
    monday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    # ... configure other days
```

### YouTube Music Track (Simplified Format)

```yaml
i1_wakeup_music:
  module: i1_wakeup_music
  class: WakeupMusic
  media_players:
    - media_player.bedroom_speaker
  music_source: "youtube_music:track:VIDEO_ID"
  initial_volume: 0.1
  target_volume: 0.5
  ramp_duration: 300
  days:
    monday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    # ... configure other days
```

### Music Assistant with Authenticated Spotify

```yaml
i1_wakeup_music:
  module: i1_wakeup_music
  class: WakeupMusic
  media_players:
    - media_player.mass_bedroom_speaker  # Music Assistant player entity
  music_source: "spotify://playlist/37i9dQZF1DX7cZxYLqLUJl"  # URI format (slashes)
  use_music_assistant: true  # Explicitly enable MA (auto-detected if not set)
  enqueue: "replace"  # Replace queue and play
  radio_mode: false  # Disable radio mode
  initial_volume: 0.1
  target_volume: 0.5
  ramp_duration: 300
  days:
    monday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    # ... configure other days
```

### Music Assistant with Spotify URL

Music Assistant also supports Spotify URLs (converted to URI format internally):

```yaml
i1_wakeup_music:
  module: i1_wakeup_music
  class: WakeupMusic
  media_players:
    - media_player.mass_bedroom_speaker
  music_source: "https://open.spotify.com/playlist/37i9dQZF1DX7cZxYLqLUJl"
  use_music_assistant: true
  initial_volume: 0.1
  target_volume: 0.5
  ramp_duration: 300
  days:
    monday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    # ... configure other days
```

### Music Assistant with Library URI

Play directly from Music Assistant's unified library:

```yaml
i1_wakeup_music:
  module: i1_wakeup_music
  class: WakeupMusic
  media_players:
    - media_player.mass_bedroom_speaker
  music_source: "library://playlist/123"  # Library URI format
  use_music_assistant: true
  initial_volume: 0.1
  target_volume: 0.5
  ramp_duration: 300
  days:
    monday:
      active: true
      start: "6:20"
      turnoff: "7:00"
    # ... configure other days
```

**Note**: Library URIs require Music Assistant. Find library item IDs in the Music Assistant UI.

## License

Proprietary - All rights reserved
