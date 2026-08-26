set launcherPath to "/Volumes/TTggg_mini01_2T/ai/筱宇短剧运营-youtube/管理系统/start-dev.command"
try
	tell application "Terminal"
		activate
		do script "exec " & quoted form of launcherPath
	end tell
on error errMsg
	display dialog "筱宇智矩启动失败：" & return & errMsg buttons {"知道了"} default button "知道了" with icon caution
end try
