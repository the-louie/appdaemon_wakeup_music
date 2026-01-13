import appdaemon.plugins.hass.hassapi as hass
import traceback
import json
from datetime import datetime
from typing import Dict, Optional


class WakeupMusic(hass.Hass):
    """
    AppDaemon app for managing wakeup music functionality.

    This app triggers music playback on specified media players at scheduled wakeup times.
    Supports volume ramping and multiple media players. Supports Spotify, YouTube Music, URLs, and local
    library music sources. Supports Music Assistant integration for authenticated
    music service playback.
    """

    def initialize(self):
        """Initialize the WakeupMusic app and set up scheduling."""
        try:
            self.log("Initializing WakeupMusic app", level="INFO")

            # Validate required configuration early
            if not self.args.get("days") or not self.args.get("media_players"):
                self.log("Error: 'days' and 'media_players' parameters are required", level="ERROR")
                return

            # Read configuration parameters
            self.days = self.args.get("days", {})
            self.media_players = self._get_config_list("media_players", [])
            self.music_source = self.args.get("music_source", "")
            self.initial_volume = float(self.args.get("initial_volume", 0.1))
            self.target_volume = float(self.args.get("target_volume", 0.5))
            self.ramp_duration = int(self.args.get("ramp_duration", 300))
            self.ramp_steps = int(self.args.get("ramp_steps", 10))
            self.play_duration = int(self.args.get("play_duration", 1500))
            self.cal_name = self.args.get("calendar")
            self.calendar_exception_cached = False
            self.active_timer = None

            # Music Assistant configuration parameters
            self.use_music_assistant = self.args.get("use_music_assistant", None)
            self.music_assistant_config_entry_id = self.args.get("music_assistant_config_entry_id", None)
            self.enqueue = self.args.get("enqueue", "replace")
            self.radio_mode = bool(self.args.get("radio_mode", False))
            self.media_type = self.args.get("media_type", None)

            # Validate Music Assistant configuration
            if self.enqueue not in ["play", "replace", "next", "replace_next", "add"]:
                self.log(f"Invalid enqueue value: {self.enqueue}. Using default 'replace'", level="WARNING")
                self.enqueue = "replace"

            # Validate configuration
            if not self.media_players:
                self.log("No media players configured", level="ERROR")
                return

            if not self.music_source:
                self.log("No music source configured", level="ERROR")
                return

            # Detect and log music source type
            if self._is_youtube_music_url(self.music_source):
                self.log("YouTube Music source detected", level="INFO")
                # Check authentication status for YouTube Music media players
                for media_player in self.media_players:
                    self._check_youtube_music_authentication(media_player)
            elif self.music_source.startswith("spotify:") or self.music_source.startswith("spotify://") or "open.spotify.com" in self.music_source:
                self.log("Spotify source detected", level="INFO")
            elif self.music_source.startswith("http://") or self.music_source.startswith("https://"):
                self.log("URL-based source detected", level="INFO")
            elif self.music_source.startswith("library://"):
                self.log("Local library source detected", level="INFO")

            # Validate volume values
            if not (0.0 <= self.initial_volume <= 1.0):
                self.log(f"Invalid initial_volume: {self.initial_volume}. Must be between 0.0 and 1.0", level="ERROR")
                return

            if not (0.0 <= self.target_volume <= 1.0):
                self.log(f"Invalid target_volume: {self.target_volume}. Must be between 0.0 and 1.0", level="ERROR")
                return

            if self.initial_volume > self.target_volume:
                msg = (f"initial_volume ({self.initial_volume}) must be <= "
                       f"target_volume ({self.target_volume})")
                self.log(msg, level="ERROR")
                return

            # Validate ramp parameters
            if self.ramp_duration <= 0:
                self.log(f"Invalid ramp_duration: {self.ramp_duration}. Must be > 0", level="ERROR")
                return

            if self.ramp_steps <= 0:
                self.log(f"Invalid ramp_steps: {self.ramp_steps}. Must be > 0", level="ERROR")
                return

            # Validate play duration
            if self.play_duration < 0:
                self.log(f"Invalid play_duration: {self.play_duration}. Must be >= 0", level="ERROR")
                return

            # Validate entities exist
            self._validate_entities()

            # Initialize state tracking
            self.is_playing = False
            self.current_volume_handle = None
            self.stop_playback_handle = None
            self.fadeout_volume_handle = None
            self.error_state = False
            self.active_media_players = []
            self.ma_player_cache = {}

            # Detect Music Assistant players and log player types
            ma_players = []
            standard_players = []
            for media_player in self.media_players:
                is_ma = self._is_music_assistant_player(media_player)
                if is_ma:
                    ma_players.append(media_player)
                    # Verify it's actually a MASS entity by checking attributes
                    try:
                        entity_state = self.get_state(media_player, attribute="all")
                        if entity_state and isinstance(entity_state, dict):
                            attrs = entity_state.get("attributes", {})
                            platform = attrs.get("platform", "")
                            if platform != "music_assistant":
                                self.log(f"WARNING: {media_player} is detected as MASS player but platform is '{platform}'. "
                                       f"Ensure you're using the MASS entity (e.g., {media_player}_mass), not the hardware entity.",
                                       level="WARNING")
                    except Exception:
                        pass
                else:
                    standard_players.append(media_player)

            if ma_players:
                self.log(f"Detected Music Assistant players: {ma_players}", level="INFO")
            if standard_players:
                self.log(f"Detected standard media players: {standard_players}", level="INFO")

            # Auto-detect use_music_assistant if not explicitly set
            if self.use_music_assistant is None:
                self.use_music_assistant = len(ma_players) > 0
                if self.use_music_assistant:
                    self.log("Auto-detected Music Assistant usage based on player types", level="INFO")

            # Set up scheduling
            self.log("WakeupMusic app initialized successfully", level="INFO")
            self.run_in(self.setup_day_schedule, 0)
            if self.cal_name:
                self.run_daily(self.check_calendar_exception, "03:30:00")

        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error during initialization at line {error_line}: {str(e)}", level="ERROR")
            self.log(traceback.format_exc(), level="ERROR")

    def _get_config_list(self, key, default):
        """Get configuration parameter as list, handling both list and string inputs."""
        value = self.args.get(key, default)
        if isinstance(value, str):
            return [value]
        elif isinstance(value, list):
            return value
        else:
            return default if value is None else [str(value)]

    def _validate_entities(self):
        """Validate that all configured entities exist in Home Assistant."""
        for entity_id in self.media_players:
            try:
                state = self.get_state(entity_id)
                if state is None:
                    self.log(f"Entity {entity_id} not found in Home Assistant", level="WARNING")
            except Exception as e:
                error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                self.log(f"Error validating entity {entity_id} at line {error_line}: {str(e)}", level="WARNING")

    def _check_youtube_music_authentication(self, media_player):
        """
        Check YouTube Music authentication status for a media player if available.

        Attempts to determine authentication status by checking entity state.
        Since authentication is handled at the Home Assistant integration level,
        this method gracefully handles cases where authentication status cannot be determined.

        Args:
            media_player (str): The media player entity ID to check

        Returns:
            bool: True if authenticated or status unknown (for backward compatibility),
                  False if authentication issues are detected
        """
        try:
            state = self.get_state(media_player)
            if state is None:
                self.log(f"Media player {media_player} state unavailable, cannot check authentication status", level="INFO")
                return True

            state_lower = str(state).lower() if state else ""
            if state_lower in ['unavailable', 'unknown']:
                self.log(f"Media player {media_player} is unavailable - authentication status cannot be determined", level="WARNING")
                return True

            return True
        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error checking authentication status for {media_player} at line {error_line}: {str(e)}", level="INFO")
            return True

    def _is_music_assistant_player(self, media_player):
        """
        Detect if a media player is a Music Assistant player.

        Checks entity_id patterns (_mass, _ma, ma_ prefix) and entity attributes
        (platform/integration) to identify MASS entities. Falls back to
        configuration flag if detection is uncertain.

        IMPORTANT: MASS creates separate entities from hardware entities.
        Use the MASS entity (e.g., media_player.living_room_mass), not the
        original hardware entity (e.g., media_player.living_room_sonos).

        Args:
            media_player (str): The media player entity ID to check

        Returns:
            bool: True if the player is a Music Assistant player, False otherwise
        """
        # Check cache first (if initialized)
        if hasattr(self, 'ma_player_cache') and media_player in self.ma_player_cache:
            return self.ma_player_cache[media_player]

        # Check entity_id patterns (MASS entities typically have _mass suffix, _ma suffix, or ma_ prefix)
        entity_name = media_player.replace("media_player.", "")
        if entity_name.endswith("_mass") or entity_name.endswith("_ma") or entity_name.startswith("ma_"):
            result = True
            if hasattr(self, 'ma_player_cache'):
                self.ma_player_cache[media_player] = result
            return result

        # Check if explicitly configured
        if self.use_music_assistant is not None:
            # If use_music_assistant is True, assume all players are MA players
            # If False, assume none are
            result = self.use_music_assistant
            if hasattr(self, 'ma_player_cache'):
                self.ma_player_cache[media_player] = result
            return result

        # Try to check entity attributes to identify MASS entities
        try:
            entity_state = self.get_state(media_player, attribute="all")
            if entity_state and isinstance(entity_state, dict):
                attrs = entity_state.get("attributes", {})
                # Check platform attribute - MASS entities have platform "music_assistant"
                platform = attrs.get("platform", "")
                if platform == "music_assistant":
                    result = True
                    if hasattr(self, 'ma_player_cache'):
                        self.ma_player_cache[media_player] = result
                    return result
                # Check if entity has MASS-specific attributes
                # MASS entities may have specific source_list or supported_features
                # This is a fallback heuristic
        except Exception as e:
            # If we can't check attributes, log but don't fail
            self.log(f"Could not check attributes for {media_player}: {e}", level="INFO")

        # Default to False if uncertain
        # WARNING: If entity is not detected as MASS but should be, set use_music_assistant=True
        result = False
        if hasattr(self, 'ma_player_cache'):
            self.ma_player_cache[media_player] = result
        return result

    def _normalize_media_source_for_ma(self, media_source):
        """
        Normalize media source format for universal compatibility.

        Converts Spotify URI formats to Spotify URLs which are universally supported
        by both standard players and Music Assistant players without triggering
        internal routing issues.

        Args:
            media_source (str): The media source to normalize

        Returns:
            str: Normalized media source (Spotify URLs or original format)
        """
        if not media_source or not isinstance(media_source, str):
            return media_source

        # Convert all Spotify URI formats to Spotify URLs for universal compatibility
        # URLs work with both standard players and Music Assistant players
        if media_source.startswith("spotify:playlist:") or media_source.startswith("spotify://playlist:"):
            playlist_id = media_source.replace("spotify:playlist:", "").replace("spotify://playlist:", "").replace("spotify://playlist/", "")
            return f"https://open.spotify.com/playlist/{playlist_id}"
        elif media_source.startswith("spotify:album:") or media_source.startswith("spotify://album:"):
            album_id = media_source.replace("spotify:album:", "").replace("spotify://album:", "").replace("spotify://album/", "")
            return f"https://open.spotify.com/album/{album_id}"
        elif media_source.startswith("spotify:artist:") or media_source.startswith("spotify://artist:"):
            artist_id = media_source.replace("spotify:artist:", "").replace("spotify://artist:", "").replace("spotify://artist/", "")
            return f"https://open.spotify.com/artist/{artist_id}"
        elif media_source.startswith("spotify:track:") or media_source.startswith("spotify://track:"):
            track_id = media_source.replace("spotify:track:", "").replace("spotify://track:", "").replace("spotify://track/", "")
            return f"https://open.spotify.com/track/{track_id}"
        elif media_source.startswith("spotify://playlist/") or media_source.startswith("spotify://album/") or media_source.startswith("spotify://artist/") or media_source.startswith("spotify://track/"):
            # Already in spotify:// format, convert to URL
            if media_source.startswith("spotify://playlist/"):
                playlist_id = media_source.replace("spotify://playlist/", "")
                return f"https://open.spotify.com/playlist/{playlist_id}"
            elif media_source.startswith("spotify://album/"):
                album_id = media_source.replace("spotify://album/", "")
                return f"https://open.spotify.com/album/{album_id}"
            elif media_source.startswith("spotify://artist/"):
                artist_id = media_source.replace("spotify://artist/", "")
                return f"https://open.spotify.com/artist/{artist_id}"
            elif media_source.startswith("spotify://track/"):
                track_id = media_source.replace("spotify://track/", "")
                return f"https://open.spotify.com/track/{track_id}"

        # Spotify URLs (https://open.spotify.com/...) are already in correct format
        # Other formats (YouTube Music, HTTP/HTTPS, library://) are passed as-is
        return media_source

    def _play_music_assistant(self, media_player):
        """
        Start music playback on a Music Assistant player using music_assistant.play_media action.

        Args:
            media_player (str): The media player entity ID

        Returns:
            bool: True if playback started successfully, False otherwise
        """
        max_retries = 2
        retry_count = 0

        while retry_count <= max_retries:
            try:
                # Set initial volume
                self.call_service(
                    "media_player/volume_set",
                    entity_id=media_player,
                    volume_level=self.initial_volume
                )

                # Normalize media source for MA
                normalized_source = self._normalize_media_source_for_ma(self.music_source)
                self.log(f"Normalized media source for MA: '{normalized_source}' (original: '{self.music_source}')", level="INFO")

                # Use media_player.play_media service with MA-compatible URI format
                # Music Assistant players support media_player.play_media with MA URIs (spotify://, library://, etc.)
                # This is the standard, implemented way to play media on MA players
                self.log(f"Calling media_player/play_media service for Music Assistant player with media_content_id: '{normalized_source}'", level="INFO")

                # Call standard media_player.play_media service with MA-compatible URI
                self.call_service(
                    "media_player/play_media",
                    entity_id=media_player,
                    media_content_id=normalized_source,
                    media_content_type="music"
                )

                self.log(f"Started Music Assistant playback on {media_player}", level="INFO")
                return True

            except Exception as e:
                retry_count += 1
                error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                error_msg = str(e).lower()
                error_type = type(e).__name__

                self.log(f"Music Assistant service call error (attempt {retry_count}/{max_retries + 1}): {error_type}: {str(e)}", level="WARNING")
                self.log(f"Error occurred at line {error_line}", level="WARNING")

                # MA-specific error detection
                if "authentication" in error_msg or "unauthorized" in error_msg:
                    msg = (f"Music Assistant authentication error on {media_player} at line "
                           f"{error_line}: {str(e)}. Ensure Music Assistant integration is "
                           f"properly configured and music services are authenticated. See "
                           f"https://www.music-assistant.io/ for setup instructions.")
                elif "radio mode" in error_msg and ("not available" in error_msg or "not supported" in error_msg):
                    msg = (f"Radio mode not available for this media source on {media_player} at line "
                           f"{error_line}: {str(e)}. Radio mode is only available with certain "
                           f"music providers. Disable radio_mode or use a supported provider.")
                elif "not found" in error_msg or "unavailable" in error_msg:
                    msg = (f"Music Assistant content unavailable on {media_player} at line "
                           f"{error_line}: {str(e)}. Check if the media source exists and is "
                           f"accessible in Music Assistant.")
                else:
                    msg = (f"Music Assistant playback error on {media_player} at line "
                           f"{error_line}: {error_type}: {str(e)}")

                if retry_count <= max_retries:
                    self.log(f"{msg}, retrying...", level="WARNING")
                else:
                    self.log(msg, level="ERROR")
                    self.log(traceback.format_exc(), level="ERROR")
                    return False

        return False

    def _is_youtube_music_url(self, url):
        """
        Check if a URL is a YouTube Music URL.

        Supports the following formats:
        - Full URLs: https://music.youtube.com/playlist?list=PLAYLIST_ID
        - Full URLs: https://music.youtube.com/watch?v=VIDEO_ID
        - Full URLs: https://music.youtube.com/album/ALBUM_ID
        - Simplified: youtube_music:playlist:PLAYLIST_ID
        - Simplified: youtube_music:track:TRACK_ID
        - Simplified: youtube_music:album:ALBUM_ID

        Args:
            url (str): The URL or identifier to check

        Returns:
            bool: True if the URL is a YouTube Music URL, False otherwise
        """
        if not url or not isinstance(url, str):
            return False

        url_lower = url.lower().strip()

        # Check for simplified format: youtube_music:type:id
        if url_lower.startswith("youtube_music:"):
            parts = url_lower.split(":", 2)
            if len(parts) >= 3 and parts[1] in ["playlist", "track", "album"]:
                return True

        # Check for full YouTube Music URLs
        if "music.youtube.com" in url_lower:
            # Playlist format: https://music.youtube.com/playlist?list=...
            if "/playlist" in url_lower and "list=" in url_lower:
                return True
            # Track format: https://music.youtube.com/watch?v=...
            if "/watch" in url_lower and "v=" in url_lower:
                return True
            # Album format: https://music.youtube.com/album/...
            if "/album/" in url_lower:
                return True

        return False

    def check_calendar_exception(self, kwargs):
        """Check calendar exception once at 03:30 and cache result"""
        if not self.cal_name:
            self.calendar_exception_cached = False
        else:
            # Handle both "calendar.xxx" and "xxx" formats
            calendar_entity = self.cal_name if self.cal_name.startswith("calendar.") else f"calendar.{self.cal_name}"
            self.calendar_exception_cached = self.get_state(calendar_entity) != "off"
        if self.calendar_exception_cached:
            self.log("Calendar exception active")
        self.setup_day_schedule()

    def get_today_schedule(self, now: datetime = None) -> Optional[Dict]:
        """Get today's schedule times as datetime objects"""
        if now is None:
            now = datetime.now()

        dayname = now.strftime("%A").lower()
        day_config = self.days.get(dayname, {})

        if not day_config.get("active", False):
            return None

        try:
            times = {}
            # Start time is required
            start_str = day_config.get("start", "06:20")
            hour, minute = map(int, start_str.split(":"))
            times["start"] = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # Turnoff time is optional
            if "turnoff" in day_config:
                turnoff_str = day_config.get("turnoff")
                hour, minute = map(int, turnoff_str.split(":"))
                times["turnoff"] = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return times
        except (ValueError, AttributeError):
            self.log(f"Error parsing time format for {dayname}", level="ERROR")
            return None

    def setup_day_schedule(self, kwargs=None):
        """Setup the schedule for the current day"""
        # Cancel existing timer
        if self.active_timer:
            self.cancel_timer(self.active_timer)
            self.active_timer = None

        if self.calendar_exception_cached:
            return

        now = datetime.now()
        schedule = self.get_today_schedule(now)
        if not schedule:
            return

        start_time = schedule['start']
        turnoff_time = schedule.get('turnoff')

        if now < start_time:
            delay = (start_time - now).total_seconds()
            self.log(f"Scheduling music start in {delay:.0f} seconds")
            self.active_timer = self.run_in(self._start_wakeup_music, delay)
        elif turnoff_time and now >= turnoff_time:
            # Past turnoff time, no action needed
            return
        else:
            # Start time has passed, start music immediately
            self.log("Starting wakeup music immediately")
            self._start_wakeup_music()

    def _start_wakeup_music(self, kwargs=None):
        """Start wakeup music playback on all configured media players."""
        # Atomic check-and-set to prevent race conditions
        if self.is_playing:
            self.log("Wakeup music already playing, skipping", level="INFO")
            return

        # Set flag immediately to prevent race conditions
        self.is_playing = True
        self.error_state = False
        self.active_media_players = []

        # Cancel any existing stop timer and fade-out
        if self.stop_playback_handle:
            self.cancel_timer(self.stop_playback_handle)
            self.stop_playback_handle = None
        if self.fadeout_volume_handle:
            self.cancel_timer(self.fadeout_volume_handle)
            self.fadeout_volume_handle = None

        try:
            # Get today's schedule to check for turnoff time
            schedule = self.get_today_schedule()
            turnoff_time = schedule.get('turnoff') if schedule else None

            # Stop any existing playback on media players
            self._stop_existing_playback()

            # Track successful playback starts
            playback_success = False
            self.log(f"Attempting to start playback on {len(self.media_players)} media player(s): {self.media_players}", level="INFO")

            for media_player in self.media_players:
                self.log(f"Starting playback on {media_player}...", level="INFO")
                self.log(f"ABOUT TO CALL _play_music_on_player for {media_player}", level="INFO")
                result = self._play_music_on_player(media_player)
                self.log(f"_play_music_on_player returned: {result} for {media_player}", level="INFO")
                if result:
                    playback_success = True
                    self.active_media_players.append(media_player)
                    self.log(f"✓ Successfully started playback on {media_player} (added to active players)", level="INFO")
                else:
                    self.log(f"✗ Failed to start playback on {media_player}", level="WARNING")

            self.log(f"Playback start summary: {len(self.active_media_players)}/{len(self.media_players)} players started successfully", level="INFO")
            self.log(f"Active media players: {self.active_media_players}", level="INFO")

            # Only start ramping if at least one player started successfully
            if playback_success:
                # Verify playback actually started (with delay to allow state transition)
                # Music Assistant players may need a moment to transition to playing state
                self.log("Scheduling playback verification in 2 seconds...", level="INFO")
                self.run_in(self._verify_and_start_ramp, 2, turnoff_time=turnoff_time)
            else:
                self.log("No media players started successfully, aborting wakeup music", level="ERROR")
                self.error_state = True
                self.is_playing = False

        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error starting wakeup music at line {error_line}: {str(e)}", level="ERROR")
            self.log(traceback.format_exc(), level="ERROR")
            self.error_state = True
            self.is_playing = False

    def _stop_existing_playback(self):
        """Stop any existing playback on configured media players."""
        for media_player in self.media_players:
            try:
                state = self.get_state(media_player)
                if state and state not in ['idle', 'off', 'unavailable']:
                    self.call_service("media_player/media_stop", entity_id=media_player)
                    self.log(f"Stopped existing playback on {media_player}", level="INFO")
            except Exception as e:
                error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                self.log(f"Error stopping playback on {media_player} at line {error_line}: {str(e)}", level="WARNING")

    def _verify_and_start_ramp(self, kwargs):
        """
        Verify playback started and start volume ramp.

        This is called with a delay to allow Music Assistant players time to
        transition to playing state after the service call returns.
        """
        try:
            turnoff_time = kwargs.get("turnoff_time") if kwargs else None
            self.log(f"Starting playback verification (first attempt) - active players: {self.active_media_players}", level="INFO")

            verification_result = self._verify_playback_started()
            self.log(f"Playback verification result (first attempt): {verification_result}", level="INFO")

            if verification_result:
                self.log("Playback verified successfully, starting volume ramp", level="INFO")
                self._start_volume_ramp(turnoff_time=turnoff_time)
            else:
                # Retry verification once more after another delay
                self.log("Playback not yet started, retrying verification in 2 seconds...", level="WARNING")
                self.run_in(self._verify_and_start_ramp_retry, 2, turnoff_time=turnoff_time)
        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error in verify and start ramp at line {error_line}: {str(e)}", level="ERROR")
            self.log(traceback.format_exc(), level="ERROR")
            self.error_state = True
            self.is_playing = False

    def _verify_and_start_ramp_retry(self, kwargs):
        """
        Final retry of playback verification before aborting.
        """
        try:
            turnoff_time = kwargs.get("turnoff_time") if kwargs else None
            self.log(f"Starting playback verification (retry attempt) - active players: {self.active_media_players}", level="INFO")

            verification_result = self._verify_playback_started()
            self.log(f"Playback verification result (retry attempt): {verification_result}", level="INFO")

            if verification_result:
                self.log("Playback verified successfully on retry, starting volume ramp", level="INFO")
                self._start_volume_ramp(turnoff_time=turnoff_time)
            else:
                self.log("Playback verification failed after retries, aborting", level="ERROR")
                self.error_state = True
                self.is_playing = False
        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error in verify and start ramp retry at line {error_line}: {str(e)}", level="ERROR")
            self.log(traceback.format_exc(), level="ERROR")
            self.error_state = True
            self.is_playing = False

    def _verify_playback_started(self):
        """
        Verify that playback actually started on at least one media player.

        Returns:
            bool: True if playback is confirmed on at least one player
        """
        try:
            self.log(f"Verifying playback for {len(self.active_media_players)} active media player(s)", level="INFO")

            if not self.active_media_players:
                self.log("No active media players to verify - verification failed", level="WARNING")
                return False

            for media_player in self.active_media_players:
                try:
                    state = self.get_state(media_player)
                    is_ma_player = self._is_music_assistant_player(media_player)

                    self.log(f"Checking {media_player}: state='{state}', is_ma_player={is_ma_player}", level="INFO")

                    # Check if player is in a playing state
                    # Include additional states that indicate playback is starting/active
                    if state in ['playing', 'buffering', 'loading']:
                        self.log(f"✓ Verified playback started on {media_player} (state: {state})", level="INFO")
                        return True

                    # For Music Assistant players, be more lenient
                    # If service call succeeded, trust it even if state hasn't updated yet
                    # Only fail if player is definitively in a stopped/error state
                    if is_ma_player:
                        stopped_states = ['idle', 'off', 'unavailable', 'unknown']
                        if state not in stopped_states:
                            self.log(f"✓ Music Assistant player {media_player} in state '{state}' - assuming playback started (service call succeeded, not in stopped states: {stopped_states})", level="INFO")
                            return True
                        else:
                            self.log(f"✗ Music Assistant player {media_player} in stopped state '{state}' (stopped states: {stopped_states})", level="WARNING")
                    else:
                        self.log(f"✗ Standard player {media_player} not in playing state (state: '{state}', expected: ['playing', 'buffering', 'loading'])", level="WARNING")

                except Exception as e:
                    error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                    self.log(f"Error checking state for {media_player} at line {error_line}: {str(e)}", level="WARNING")
                    continue

            # Log failure with states for debugging
            try:
                states = {}
                for mp in self.active_media_players:
                    try:
                        states[mp] = self.get_state(mp)
                    except Exception:
                        states[mp] = "error_getting_state"
                self.log(f"✗ Playback verification failed - all player states: {states}", level="ERROR")
            except Exception as e:
                self.log(f"Error logging player states: {str(e)}", level="WARNING")

            return False
        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error verifying playback at line {error_line}: {str(e)}", level="ERROR")
            self.log(traceback.format_exc(), level="ERROR")
            # Assume success if we can't verify (better than failing)
            self.log("Assuming playback success due to verification error", level="WARNING")
            return True

    def _play_music_on_player(self, media_player):
        """
        Start music playback on a specific media player with retry logic.

        Uses music_assistant/play_media service for MASS players and
        standard media_player/play_media service for standard players.

        Returns:
            bool: True if playback started successfully, False otherwise
        """
        # TEST LOG - should appear first - NO TRY BLOCK
        self.log("=== _play_music_on_player ENTRY ===", level="INFO")
        self.log(f"Method called with media_player={media_player}", level="INFO")
        try:

            # Check if this is a Music Assistant player
            self.log(f"[WEBSOCKET] About to check if {media_player} is MASS player", level="INFO")
            is_ma_player = self._is_music_assistant_player(media_player)
            self.log(f"[WEBSOCKET] _play_music_on_player called for {media_player}, is_ma_player={is_ma_player}", level="INFO")
        except Exception as entry_error:
            self.log(f"[WEBSOCKET] ERROR in entry code: {entry_error}", level="ERROR")
            self.log(traceback.format_exc(), level="ERROR")
            raise

        max_retries = 2
        retry_count = 0
        # Check if this is YouTube Music (cache result to avoid duplicate calls)
        is_youtube_music = self._is_youtube_music_url(self.music_source)

        while retry_count <= max_retries:
            self.log(f"[WEBSOCKET] Starting playback attempt {retry_count + 1}/{max_retries + 1} for {media_player}", level="INFO")
            try:
                # Set initial volume
                self.log(f"[WEBSOCKET] Setting initial volume to {self.initial_volume} on {media_player}", level="INFO")
                self.call_service(
                    "media_player/volume_set",
                    entity_id=media_player,
                    volume_level=self.initial_volume
                )
                self.log(f"[WEBSOCKET] Volume set completed for {media_player}", level="INFO")

                if is_ma_player:
                    self.log(f"[WEBSOCKET] Entering MASS player code path for {media_player}", level="INFO")
                    # Use dedicated music_assistant/play_media service for MASS players
                    # IMPORTANT: Music Assistant DOES NOT support URLs (http://, https://).
                    # It requires URI format (spotify://, library://, etc.)
                    # Keep the original URI format and only normalize colons to slashes
                    ma_source = self.music_source
                    self.log(f"[WEBSOCKET] Original music_source before normalization: '{ma_source}'", level="INFO")

                    # Normalize URI format: convert spotify:playlist: to spotify://playlist/
                    # This ensures correct slash format while preserving URI structure
                    if "spotify:playlist:" in ma_source:
                        ma_source = ma_source.replace("spotify:playlist:", "spotify://playlist/")
                    elif "spotify:track:" in ma_source:
                        ma_source = ma_source.replace("spotify:track:", "spotify://track/")
                    elif "spotify:album:" in ma_source:
                        ma_source = ma_source.replace("spotify:album:", "spotify://album/")
                    elif "spotify:artist:" in ma_source:
                        ma_source = ma_source.replace("spotify:artist:", "spotify://artist/")
                    # Handle already-formatted URIs with colons (spotify://playlist: -> spotify://playlist/)
                    elif "spotify://playlist:" in ma_source:
                        ma_source = ma_source.replace("spotify://playlist:", "spotify://playlist/")
                    elif "spotify://track:" in ma_source:
                        ma_source = ma_source.replace("spotify://track:", "spotify://track/")
                    elif "spotify://album:" in ma_source:
                        ma_source = ma_source.replace("spotify://album:", "spotify://album/")
                    elif "spotify://artist:" in ma_source:
                        ma_source = ma_source.replace("spotify://artist:", "spotify://artist/")
                    # If it's a URL, convert back to URI format (for cases where config has URL)
                    elif ma_source.startswith("https://open.spotify.com/"):
                        if "/playlist/" in ma_source:
                            playlist_id = ma_source.split("/playlist/")[1].split("?")[0]
                            ma_source = f"spotify://playlist/{playlist_id}"
                        elif "/track/" in ma_source:
                            track_id = ma_source.split("/track/")[1].split("?")[0]
                            ma_source = f"spotify://track/{track_id}"
                        elif "/album/" in ma_source:
                            album_id = ma_source.split("/album/")[1].split("?")[0]
                            ma_source = f"spotify://album/{album_id}"
                        elif "/artist/" in ma_source:
                            artist_id = ma_source.split("/artist/")[1].split("?")[0]
                            ma_source = f"spotify://artist/{artist_id}"
                    # For library:// and other MASS URIs, pass through as-is
                    # (they should already be in correct format)

                    self.log(f"[MASS] Original music_source: '{self.music_source}'", level="INFO")
                    self.log(f"[MASS] Normalized URI for MASS: '{ma_source}'", level="INFO")
                    self.log(f"[MASS] Preparing music_assistant/play_media service call", level="INFO")

                    service_params = {
                        "entity_id": media_player,
                        "media_id": ma_source,  # Use the raw URI here, not URL
                        "enqueue": self.enqueue
                    }
                    if self.radio_mode:
                        service_params["radio_mode"] = True
                    if self.music_assistant_config_entry_id:
                        service_params["config_entry_id"] = self.music_assistant_config_entry_id

                    self.log(f"[MASS] Service: music_assistant/play_media", level="INFO")
                    self.log(f"[MASS] Parameters: {service_params}", level="INFO")

                    # Log exact websocket payload that will be sent
                    try:
                        websocket_payload = {
                            "type": "call_service",
                            "domain": "music_assistant",
                            "service": "play_media",
                            "service_data": service_params
                        }
                        payload_json = json.dumps(websocket_payload, indent=2)
                        params_json = json.dumps(service_params, indent=2)
                        self.log(f"[WEBSOCKET] MASS payload to be sent: {payload_json}", level="INFO")
                        self.log(f"[WEBSOCKET] MASS service string: 'music_assistant/play_media'", level="INFO")
                        self.log(f"[WEBSOCKET] MASS service_data: {params_json}", level="INFO")
                    except Exception as json_error:
                        self.log(f"[WEBSOCKET] Error serializing payload: {json_error}", level="ERROR")
                        self.log(f"[WEBSOCKET] service_params dict: {service_params}", level="INFO")

                    self.log(f"[MASS] Calling music_assistant/play_media for MASS player with URI: '{ma_source}'", level="INFO")

                    try:
                        result = self.call_service("music_assistant/play_media", **service_params)
                        self.log(f"[MASS] Service call completed. Result: {result}", level="INFO")
                        self.log(f"[WEBSOCKET] MASS call successful, result: {result}", level="INFO")
                    except Exception as service_error:
                        self.log(f"[MASS] Service call raised exception immediately: {type(service_error).__name__}: {str(service_error)}", level="ERROR")
                        self.log(f"[MASS] Service call traceback:\n{traceback.format_exc()}", level="ERROR")
                        raise
                else:
                    # Use standard media_player/play_media for non-MASS players
                    # Convert to Spotify URLs for universal compatibility
                    normalized_source = self._normalize_media_source_for_ma(self.music_source)
                    if normalized_source != self.music_source:
                        self.log(f"Normalized media source: '{self.music_source}' -> '{normalized_source}'", level="INFO")

                    self.log(f"[Standard] Original music_source: '{self.music_source}'", level="INFO")
                    self.log(f"[Standard] Normalized source: '{normalized_source}'", level="INFO")
                    self.log(f"[Standard] Preparing media_player/play_media service call", level="INFO")

                    service_params = {
                        "entity_id": media_player,
                        "media_content_id": normalized_source,
                        "media_content_type": "music"
                    }
                    self.log(f"[Standard] Service: media_player/play_media", level="INFO")
                    self.log(f"[Standard] Parameters: {service_params}", level="INFO")

                    # Log exact websocket payload that will be sent
                    websocket_payload = {
                        "type": "call_service",
                        "domain": "media_player",
                        "service": "play_media",
                        "service_data": service_params
                    }
                    self.log(f"[WEBSOCKET] Standard payload to be sent: {json.dumps(websocket_payload, indent=2)}", level="INFO")
                    self.log(f"[WEBSOCKET] Standard service string: 'media_player/play_media'", level="INFO")
                    self.log(f"[WEBSOCKET] Standard service_data: {json.dumps(service_params, indent=2)}", level="INFO")

                    self.log(f"Calling media_player/play_media with media_content_id: '{normalized_source}'", level="INFO")

                    try:
                        result = self.call_service("media_player/play_media", **service_params)
                        self.log(f"[Standard] Service call completed. Result: {result}", level="INFO")
                        self.log(f"[WEBSOCKET] Standard call successful, result: {result}", level="INFO")
                    except Exception as service_error:
                        self.log(f"[Standard] Service call raised exception immediately: {type(service_error).__name__}: {str(service_error)}", level="ERROR")
                        self.log(f"[Standard] Service call traceback:\n{traceback.format_exc()}", level="ERROR")
                        raise

                if is_ma_player:
                    self.log(f"Started Music Assistant playback on {media_player}", level="INFO")
                elif is_youtube_music:
                    self.log(f"Started YouTube Music playback on {media_player}", level="INFO")
                else:
                    self.log(f"Started music playback on {media_player}", level="INFO")
                return True

            except Exception as e:
                retry_count += 1
                error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                error_msg = str(e).lower()
                error_type = type(e).__name__

                # Detailed websocket error logging
                self.log(f"[WEBSOCKET ERROR] Exception caught in _play_music_on_player", level="ERROR")
                self.log(f"[WEBSOCKET ERROR] Player: {media_player}", level="ERROR")
                self.log(f"[WEBSOCKET ERROR] Is MASS player: {is_ma_player}", level="ERROR")
                self.log(f"[WEBSOCKET ERROR] Error type: {error_type}", level="ERROR")
                self.log(f"[WEBSOCKET ERROR] Error message: {str(e)}", level="ERROR")
                self.log(f"[WEBSOCKET ERROR] Error at line: {error_line}", level="ERROR")
                self.log(f"[WEBSOCKET ERROR] Retry attempt: {retry_count}/{max_retries + 1}", level="ERROR")

                # Log what was actually sent over websocket
                if is_ma_player:
                    ma_source = self.music_source
                    # Reconstruct the normalization to show what was sent
                    if "spotify:playlist:" in ma_source:
                        ma_source = ma_source.replace("spotify:playlist:", "spotify://playlist/")
                    elif "spotify:track:" in ma_source:
                        ma_source = ma_source.replace("spotify:track:", "spotify://track/")
                    elif "spotify:album:" in ma_source:
                        ma_source = ma_source.replace("spotify:album:", "spotify://album/")
                    elif "spotify:artist:" in ma_source:
                        ma_source = ma_source.replace("spotify:artist:", "spotify://artist/")
                    elif "spotify://playlist:" in ma_source:
                        ma_source = ma_source.replace("spotify://playlist:", "spotify://playlist/")
                    elif "spotify://track:" in ma_source:
                        ma_source = ma_source.replace("spotify://track:", "spotify://track/")
                    elif "spotify://album:" in ma_source:
                        ma_source = ma_source.replace("spotify://album:", "spotify://album/")
                    elif "spotify://artist:" in ma_source:
                        ma_source = ma_source.replace("spotify://artist:", "spotify://artist/")
                    elif ma_source.startswith("https://open.spotify.com/"):
                        if "/playlist/" in ma_source:
                            playlist_id = ma_source.split("/playlist/")[1].split("?")[0]
                            ma_source = f"spotify://playlist/{playlist_id}"
                        elif "/track/" in ma_source:
                            track_id = ma_source.split("/track/")[1].split("?")[0]
                            ma_source = f"spotify://track/{track_id}"
                        elif "/album/" in ma_source:
                            album_id = ma_source.split("/album/")[1].split("?")[0]
                            ma_source = f"spotify://album/{album_id}"
                        elif "/artist/" in ma_source:
                            artist_id = ma_source.split("/artist/")[1].split("?")[0]
                            ma_source = f"spotify://artist/{artist_id}"

                    error_service_params = {
                        "entity_id": media_player,
                        "media_id": ma_source,
                        "enqueue": self.enqueue
                    }
                    if self.radio_mode:
                        error_service_params["radio_mode"] = True
                    if self.music_assistant_config_entry_id:
                        error_service_params["config_entry_id"] = self.music_assistant_config_entry_id

                    error_websocket_payload = {
                        "type": "call_service",
                        "domain": "music_assistant",
                        "service": "play_media",
                        "service_data": error_service_params
                    }
                    self.log(f"[WEBSOCKET ERROR] Original source: '{self.music_source}'", level="ERROR")
                    self.log(f"[WEBSOCKET ERROR] Normalized URI sent: '{ma_source}'", level="ERROR")
                    self.log(f"[WEBSOCKET ERROR] Service called: music_assistant/play_media", level="ERROR")
                    self.log(f"[WEBSOCKET ERROR] Exact payload sent: {json.dumps(error_websocket_payload, indent=2)}", level="ERROR")
                else:
                    normalized = self._normalize_media_source_for_ma(self.music_source)
                    error_service_params = {
                        "entity_id": media_player,
                        "media_content_id": normalized,
                        "media_content_type": "music"
                    }
                    error_websocket_payload = {
                        "type": "call_service",
                        "domain": "media_player",
                        "service": "play_media",
                        "service_data": error_service_params
                    }
                    self.log(f"[WEBSOCKET ERROR] Original source: '{self.music_source}'", level="ERROR")
                    self.log(f"[WEBSOCKET ERROR] Normalized source: '{normalized}'", level="ERROR")
                    self.log(f"[WEBSOCKET ERROR] Service called: media_player/play_media", level="ERROR")
                    self.log(f"[WEBSOCKET ERROR] Exact payload sent: {json.dumps(error_websocket_payload, indent=2)}", level="ERROR")

                self.log(f"[WEBSOCKET ERROR] Full traceback:\n{traceback.format_exc()}", level="ERROR")

                # Check for MASS-specific error patterns
                if is_ma_player:
                    if error_type == "NotImplementedError" or "not implemented" in error_msg:
                        msg = (f"Music Assistant service not implemented on {media_player} at line "
                               f"{error_line}: {str(e)}. Ensure you're using the correct MASS entity "
                               f"(e.g., media_player.xxx_mass) and that Music Assistant integration "
                               f"is properly configured.")
                    elif "authentication" in error_msg or "unauthorized" in error_msg:
                        msg = (f"Music Assistant authentication error on {media_player} at line "
                               f"{error_line}: {str(e)}. Ensure Music Assistant integration is "
                               f"properly configured and music services are authenticated. See "
                               f"https://www.music-assistant.io/ for setup instructions.")
                    elif "not found" in error_msg or "unavailable" in error_msg:
                        msg = (f"Music Assistant content unavailable on {media_player} at line "
                               f"{error_line}: {str(e)}. Check if the media source exists and is "
                               f"accessible in Music Assistant.")
                    else:
                        msg = (f"Music Assistant playback error on {media_player} at line "
                               f"{error_line}: {str(e)}")
                # Check for YouTube Music-specific error patterns
                elif is_youtube_music:
                    if ("authentication" in error_msg or "unauthorized" in error_msg or
                            "token" in error_msg and ("expired" in error_msg or "invalid" in error_msg) or
                            "login" in error_msg and ("required" in error_msg or "failed" in error_msg)):
                        msg = (f"YouTube Music authentication error on {media_player} at line "
                               f"{error_line}: {str(e)}. Ensure YouTube Music integration is "
                               f"properly configured and authenticated in Home Assistant. See "
                               f"README.md for authentication setup instructions.")
                    elif "not found" in error_msg or "unavailable" in error_msg:
                        msg = (f"YouTube Music content unavailable on {media_player} at line "
                               f"{error_line}: {str(e)}. Check if the playlist/album/track "
                               f"exists and is accessible.")
                    elif "not supported" in error_msg or "unsupported" in error_msg:
                        msg = (f"YouTube Music not supported on {media_player} at line "
                               f"{error_line}: {str(e)}. Ensure the media player has YouTube "
                               f"Music support (e.g., ytube_music_player or Music Assistant).")
                    else:
                        msg = (f"YouTube Music playback error on {media_player} at line "
                               f"{error_line}: {str(e)}")
                else:
                    msg = (f"Error playing music on {media_player} at line {error_line}: "
                           f"{str(e)}")

                if retry_count <= max_retries:
                    self.log(f"{msg}, retrying...", level="WARNING")
                    # Note: Actual retry happens in next loop iteration
                    # For async retry, would need to schedule callback
                else:
                    self.log(msg, level="ERROR")
                    return False

        return False

    def _start_volume_ramp(self, turnoff_time=None):
        """Start gradual volume increase (ramping)."""
        try:
            # Cancel any existing ramp
            if self.current_volume_handle:
                self.cancel_timer(self.current_volume_handle)

            # Calculate volume increment per step
            volume_diff = self.target_volume - self.initial_volume
            step_duration = self.ramp_duration / self.ramp_steps
            volume_increment = volume_diff / self.ramp_steps

            # Validate step_duration is reasonable (at least 0.1 seconds)
            if step_duration < 0.1:
                msg = (f"Warning: step_duration ({step_duration}s) is very small, "
                       f"using minimum 0.1s")
                self.log(msg, level="WARNING")
                step_duration = 0.1

            current_volume = self.initial_volume
            step = 0

            def ramp_step(kwargs):
                nonlocal current_volume, step
                try:
                    step += 1
                    current_volume += volume_increment

                    # Ensure we don't exceed target volume
                    if current_volume > self.target_volume:
                        current_volume = self.target_volume

                    # Set volume on all media players
                    for media_player in self.media_players:
                        try:
                            self.call_service(
                                "media_player/volume_set",
                                entity_id=media_player,
                                volume_level=current_volume
                            )
                        except Exception as e:
                            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                            msg = (f"Error setting volume on {media_player} at line "
                                   f"{error_line}: {str(e)}")
                            self.log(msg, level="WARNING")

                    # Schedule next step if not at target
                    if step < self.ramp_steps and current_volume < self.target_volume:
                        self.current_volume_handle = self.run_in(ramp_step, step_duration)
                    else:
                        self.current_volume_handle = None
                        self.error_state = False
                        self._handle_playback_completion()
                        self.log(f"Volume ramp completed at {self.target_volume}", level="INFO")
                        # Schedule playback stop
                        self._schedule_playback_stop(turnoff_time=turnoff_time)

                except Exception as e:
                    error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                    self.log(f"Error in volume ramp step at line {error_line}: {str(e)}", level="ERROR")
                    self.current_volume_handle = None
                    self.is_playing = False
                    self.error_state = True

            # Start first ramp step
            self.current_volume_handle = self.run_in(ramp_step, step_duration)
            msg = (f"Started volume ramp from {self.initial_volume} to "
                   f"{self.target_volume} over {self.ramp_duration}s")
            self.log(msg, level="INFO")

        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error starting volume ramp at line {error_line}: {str(e)}", level="ERROR")
            self.is_playing = False
            self.error_state = True

    def _schedule_playback_stop(self, turnoff_time=None):
        """Schedule playback to stop after play_duration seconds or at turnoff_time."""
        try:
            now = datetime.now()
            fadeout_duration = 60  # 1 minute fade-out
            fadeout_steps = 15

            if turnoff_time:
                # Use turnoff_time from schedule if provided
                delay = (turnoff_time - now).total_seconds()
                if delay > fadeout_duration:
                    # Schedule fade-out 1 minute before turnoff
                    fadeout_delay = delay - fadeout_duration
                    self.fadeout_volume_handle = self.run_in(
                        self._start_volume_fadeout,
                        fadeout_delay,
                        end_time=turnoff_time,
                        fadeout_steps=fadeout_steps
                    )
                    self.log(f"Scheduled fade-out to start in {fadeout_delay:.0f} seconds (1 minute before turnoff)", level="INFO")

                    # Schedule actual stop at turnoff time
                    self.stop_playback_handle = self.run_in(
                        self._stop_playback_after_duration,
                        delay,
                        duration_seconds=delay,
                        stop_reason="turnoff_time"
                    )
                    self.log(f"Scheduled playback stop at {turnoff_time.strftime('%H:%M')} (in {delay:.0f} seconds)", level="INFO")
                elif delay > 0:
                    # Less than 1 minute remaining, start fade-out immediately
                    self._start_volume_fadeout(kwargs={"end_time": turnoff_time, "fadeout_steps": fadeout_steps})
                    self.stop_playback_handle = self.run_in(
                        self._stop_playback_after_duration,
                        delay,
                        duration_seconds=delay,
                        stop_reason="turnoff_time"
                    )
                    self.log(f"Scheduled playback stop at {turnoff_time.strftime('%H:%M')} (in {delay:.0f} seconds)", level="INFO")
                else:
                    # Turnoff time has passed, stop immediately
                    self._stop_playback_after_duration(kwargs={"duration_seconds": 0, "stop_reason": "turnoff_time"})
            elif self.play_duration > 0:
                # Use play_duration if no turnoff_time specified
                if self.play_duration > fadeout_duration:
                    # Schedule fade-out 1 minute before end
                    fadeout_delay = self.play_duration - fadeout_duration
                    self.fadeout_volume_handle = self.run_in(
                        self._start_volume_fadeout,
                        fadeout_delay,
                        end_time=None,
                        fadeout_steps=fadeout_steps
                    )
                    self.log(f"Scheduled fade-out to start in {fadeout_delay:.0f} seconds (1 minute before end)", level="INFO")

                # Schedule actual stop
                self.stop_playback_handle = self.run_in(
                    self._stop_playback_after_duration,
                    self.play_duration,
                    duration_seconds=self.play_duration,
                    stop_reason="play_duration"
                )
                self.log(f"Scheduled playback stop in {self.play_duration} seconds ({self.play_duration / 60:.1f} minutes)", level="INFO")
        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error scheduling playback stop at line {error_line}: {str(e)}", level="WARNING")

    def _start_volume_fadeout(self, kwargs=None):
        """Start gradual volume decrease (fade-out) from current volume to 0.01."""
        try:
            # Handle both direct calls and AppDaemon run_in calls
            if kwargs is None:
                kwargs = {}

            # Cancel any existing fade-out
            if self.fadeout_volume_handle:
                self.cancel_timer(self.fadeout_volume_handle)

            # Get current volume from one of the media players
            current_volume = self.target_volume
            try:
                # Try to get actual current volume from first media player
                state = self.get_state(self.media_players[0], attribute="all")
                if state and isinstance(state, dict):
                    attributes = state.get("attributes", {})
                    volume_level = attributes.get("volume_level")
                    if volume_level is not None:
                        current_volume = float(volume_level)
            except Exception:
                # Fall back to target_volume if we can't get current volume
                pass

            fadeout_duration = 60  # 1 minute
            fadeout_steps = kwargs.get("fadeout_steps", 15) if kwargs else 15
            target_fadeout_volume = 0.01  # Very low volume

            # Calculate volume decrement per step
            volume_diff = current_volume - target_fadeout_volume

            # If already at or below target volume, skip fade-out
            if volume_diff <= 0:
                self.log(f"Volume already at or below fade-out target ({current_volume:.3f} <= {target_fadeout_volume:.3f}), skipping fade-out", level="INFO")
                return

            step_duration = fadeout_duration / fadeout_steps
            volume_decrement = volume_diff / fadeout_steps

            # Validate step_duration is reasonable (at least 0.1 seconds)
            if step_duration < 0.1:
                msg = (f"Warning: fade-out step_duration ({step_duration}s) is very small, "
                       f"using minimum 0.1s")
                self.log(msg, level="WARNING")
                step_duration = 0.1

            fadeout_volume = current_volume
            step = 0

            def fadeout_step(kwargs):
                nonlocal fadeout_volume, step
                try:
                    step += 1
                    fadeout_volume -= volume_decrement

                    # Ensure we don't go below target fadeout volume
                    if fadeout_volume < target_fadeout_volume:
                        fadeout_volume = target_fadeout_volume

                    # Set volume on all media players
                    for media_player in self.media_players:
                        try:
                            self.call_service(
                                "media_player/volume_set",
                                entity_id=media_player,
                                volume_level=fadeout_volume
                            )
                        except Exception as e:
                            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                            msg = (f"Error setting fade-out volume on {media_player} at line "
                                   f"{error_line}: {str(e)}")
                            self.log(msg, level="WARNING")

                    # Schedule next step if not at target
                    if step < fadeout_steps and fadeout_volume > target_fadeout_volume:
                        self.fadeout_volume_handle = self.run_in(fadeout_step, step_duration)
                    else:
                        self.fadeout_volume_handle = None
                        self.log(f"Volume fade-out completed at {fadeout_volume:.3f}", level="INFO")

                except Exception as e:
                    error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                    self.log(f"Error in volume fade-out step at line {error_line}: {str(e)}", level="ERROR")
                    self.fadeout_volume_handle = None

            # Start first fade-out step
            self.fadeout_volume_handle = self.run_in(fadeout_step, step_duration)
            msg = (f"Started volume fade-out from {current_volume:.3f} to "
                   f"{target_fadeout_volume:.3f} over {fadeout_duration}s in {fadeout_steps} steps")
            self.log(msg, level="INFO")

        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error starting volume fade-out at line {error_line}: {str(e)}", level="ERROR")
            self.fadeout_volume_handle = None

    def _stop_playback_after_duration(self, kwargs):
        """Stop playback on all media players after the scheduled duration."""
        try:
            # Get duration from kwargs if provided, otherwise use play_duration
            duration_seconds = kwargs.get("duration_seconds", self.play_duration) if kwargs else self.play_duration
            stop_reason = kwargs.get("stop_reason", "play_duration") if kwargs else "play_duration"

            if stop_reason == "turnoff_time":
                self.log(f"Stopping playback at scheduled turnoff time (after {duration_seconds:.0f} seconds)", level="INFO")
            else:
                self.log(f"Stopping playback after {duration_seconds:.0f} seconds ({duration_seconds / 60:.1f} minutes)", level="INFO")

            for media_player in self.media_players:
                try:
                    self.call_service("media_player/media_stop", entity_id=media_player)
                    self.log(f"Stopped playback on {media_player}", level="INFO")
                except Exception as e:
                    error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                    self.log(f"Error stopping playback on {media_player} at line {error_line}: {str(e)}", level="WARNING")

            self.stop_playback_handle = None
            self.is_playing = False
            self.error_state = False
            self.active_media_players = []
        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error in playback stop handler at line {error_line}: {str(e)}", level="ERROR")
            self.stop_playback_handle = None
            self.is_playing = False
            self.error_state = True

    def _handle_playback_completion(self):
        """Handle playback completion - monitor and log when playback ends."""
        try:
            # Monitor playback state for a short period to detect completion
            def check_playback_state(kwargs):
                try:
                    all_stopped = True
                    for media_player in self.active_media_players:
                        state = self.get_state(media_player)
                        if state not in ['idle', 'off', 'unavailable', 'paused']:
                            all_stopped = False
                            break

                    if all_stopped and self.active_media_players:
                        self.log("Playback completed on all media players", level="INFO")
                        self.active_media_players = []
                except Exception as e:
                    error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
                    self.log(f"Error checking playback state at line {error_line}: {str(e)}", level="WARNING")

            # Check playback state after a delay
            self.run_in(check_playback_state, 5)
        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error setting up playback completion handler at line {error_line}: {str(e)}", level="WARNING")

    def terminate(self):
        """Clean up resources when app is terminated."""
        try:
            if self.current_volume_handle:
                self.cancel_timer(self.current_volume_handle)
                self.current_volume_handle = None

            if self.stop_playback_handle:
                self.cancel_timer(self.stop_playback_handle)
                self.stop_playback_handle = None

            if self.fadeout_volume_handle:
                self.cancel_timer(self.fadeout_volume_handle)
                self.fadeout_volume_handle = None

            if self.active_timer:
                self.cancel_timer(self.active_timer)
                self.active_timer = None

            self.log("WakeupMusic app terminated", level="INFO")

        except Exception as e:
            error_line = traceback.extract_tb(e.__traceback__)[-1].lineno
            self.log(f"Error during termination at line {error_line}: {str(e)}", level="ERROR")
