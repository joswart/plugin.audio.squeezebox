#!/usr/bin/python
# -*- coding: utf-8 -*-

'''
    plugin.audio.squeezebox
    Squeezelite Player for Kodi
    player_monitor.py
    monitor both LMS and Kodi player
'''

from utils import log_msg, log_exception, ADDON_ID
import xbmc
import xbmcgui
import xbmcvfs
from urllib import quote_plus

DATA_PATH = xbmc.translatePath("special://profile/addon_data/%s/" % ADDON_ID).decode("utf-8")


class KodiPlayer(xbmc.Player):
    '''Monitor all player events in Kodi'''
    playlist = None
    trackchanging = False
    exit = False
    is_playing = False
    is_busy = False

    def __init__(self, **kwargs):
        self.lmsserver = kwargs.get("lmsserver")
        self.webport = kwargs.get("webport")
        self.playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        xbmc.Player.__init__(self)
        log_msg("Start Monitoring events for playerid %s" % self.lmsserver.playerid)

    def close(self):
        '''cleanup on exit'''
        exit = True
        del self.playlist

    def onPlayBackPaused(self):
        '''Kodi event fired when playback is paused'''
        if self.isPlayingAudio() and self.lmsserver.mode == "play" and xbmc.getInfoLabel("MusicPlayer.getProperty(sl_path)"):
            self.lmsserver.pause()
            log_msg("Playback paused")

    def onPlayBackResumed(self):
        '''Kodi event fired when playback is resumed after pause'''
        if self.isPlayingAudio() and self.lmsserver.mode == "pause" and xbmc.getInfoLabel("MusicPlayer.getProperty(sl_path)"):
            self.lmsserver.unpause()
            log_msg("Playback unpaused")

    def onPlayBackEnded(self):
        self.is_playing = False

    def onPlayBackStarted(self):
        '''Kodi event fired when playback is started (including next tracks)'''
        is_busy = True
        if self.isPlayingVideo():
            # player is now playing video ! - disable the LMS player
            self.is_playing = False
            self.lmsserver.send_command("power 0")
            log_msg("Kodi started playing video - disabled the LMS player")
        else:
            self.wait_for_player()
            # set the is_playing bool to indicate we are playing LMS content
            self.is_playing = xbmc.getCondVisibility("!IsEmpty(MusicPlayer.Property(sl_path))") == 1
            if self.is_playing and not self.lmsserver.state_changing:
                if self.playlist.getposition() != self.lmsserver.cur_index:
                    # next song requested
                    # figure out which track is requested
                    new_index = self.playlist.getposition()
                    log_msg("other track requested by kodi player - index: %s" % new_index)
                    self.lmsserver.send_command("playlist index %s" % new_index)
        is_busy = False

    def onPlayBackSpeedChanged(self, speed):
        '''Kodi event fired when player is fast forwarding/rewinding'''
        if self.isPlayingAudio() and self.lmsserver.mode == "play":
            log_msg("User is requesting to fast forward or rewind")
            if speed > 1:
                self.lmsserver.send_command("time +10")
            elif speed < 0:
                self.lmsserver.send_command("time -10")

    def cur_time(self):
        '''current time of the player - if fails return lms player time'''
        try:
            cur_time_kodi = int(self.getTime())
        except Exception:
            cur_time_kodi = self.lmsserver.time
        return cur_time_kodi

    def onPlayBackSeek(self, seekTime, seekOffset):
        '''Kodi event fired when the user is seeking'''
        if self.is_playing and not self.lmsserver.state_changing and not self.is_busy:
            self.lmsserver.send_command("time %s" % (int(seekTime) / 1000))

    def onPlayBackStopped(self):
        '''Kodi event fired when playback is stopped'''
        if self.isPlayingAudio():
            if self.lmsserver.mode == "play" or self.lmsserver.mode == "pause":
                self.lmsserver.stop()
                log_msg("playback stopped")
        self.is_playing = False

    def create_listitem(self, lms_song):
        '''Create Kodi listitem from LMS song details'''
        listitem = xbmcgui.ListItem(lms_song["title"])
        listitem.setInfo('music',
                         {
                             'title': lms_song["title"],
                             'artist': lms_song["trackartist"],
                             'album': lms_song.get("album"),
                             'duration': lms_song.get("duration"),
                             'discnumber': lms_song.get("disc"),
                             'rating': lms_song.get("rating"),
                             'genre': lms_song["genres"],
                             'tracknumber': lms_song.get("track_number"),
                             'lyrics': lms_song.get("lyrics"),
                             'year': lms_song.get("year"),
                             'comment': lms_song.get("comment")
                         })
        listitem.setArt({"thumb": lms_song["thumb"]})
        listitem.setIconImage(lms_song["thumb"])
        listitem.setThumbnailImage(lms_song["thumb"])
        if lms_song.get("remote_title") or not lms_song.get("duration") or lms_song.get("duration") == "0":
            # workaround for radio streams
            file_name = "http://127.0.0.1:%s/track/radio" % (self.webport)
        else:
            file_name = "http://127.0.0.1:%s/track/%s" % (self.webport, "%s" % int(lms_song.get("duration")))
        listitem.setProperty("sl_path", lms_song["url"])
        listitem.setContentLookup(False)
        listitem.setProperty('do_not_analyze', 'true')
        cmd = quote_plus("playlist index %s" % lms_song["playlist index"])
        org_url = "plugin://plugin.audio.squeezebox?action=command&params=%s" % cmd
        listitem.setProperty("original_listitem_url",org_url)
        return listitem, file_name

    def update_playlist(self):
        '''Update the playlist'''
        lmsplaylist = self.lmsserver.cur_playlist(True)
        if len(self.playlist) > len(lmsplaylist):
            log_msg("clearing playlist...")
            self.playlist.clear()
        for item in lmsplaylist:
            li, file_name = self.create_listitem(item)
            self.playlist.add(file_name, li, item["playlist index"])
        # refresh now playing playlist if needed
        if xbmc.getInfoLabel("Container.FolderPath") in ["playlistmusic://", "plugin://plugin.audio.squeezebox/?action=currentplaylist"]:
            xbmc.executebuiltin("Container.Refresh")

    def wait_for_player(self):
        count = 0
        xbmc.sleep(500)
        while not xbmc.getCondVisibility("Player.HasAudio") and count < 10:
            xbmc.sleep(250)
            count += 1
