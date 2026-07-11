!macro NSIS_HOOK_PREUNINSTALL
  MessageBox MB_YESNO|MB_ICONQUESTION "是否同时删除 MiaoGent 用户数据？$\r$\n$\r$\n这会删除本机草稿、AI 结果、反馈、配置、日志和缓存。QQ 邮箱服务器上的邮件不会被删除。$\r$\n$\r$\n如果你只是升级或后续还要继续使用，请选择“否”。" IDNO cleanup_done
    RMDir /r "$APPDATA\com.wuxian.qqmailagent"
    RMDir /r "$LOCALAPPDATA\com.wuxian.qqmailagent"
    nsExec::ExecToLog '"$SYSDIR\cmd.exe" /C cmdkey /delete:com.wuxian.qqmailagent 1>NUL 2>NUL'
    nsExec::ExecToLog '"$SYSDIR\cmd.exe" /C cmdkey /delete:qq-mail-auth-code 1>NUL 2>NUL'
    nsExec::ExecToLog '"$SYSDIR\cmd.exe" /C cmdkey /delete:deepseek-api-key 1>NUL 2>NUL'
    nsExec::ExecToLog '"$SYSDIR\cmd.exe" /C cmdkey /delete:com.wuxian.qqmailagent/qq-mail-auth-code 1>NUL 2>NUL'
    nsExec::ExecToLog '"$SYSDIR\cmd.exe" /C cmdkey /delete:com.wuxian.qqmailagent/deepseek-api-key 1>NUL 2>NUL'
  cleanup_done:
!macroend
