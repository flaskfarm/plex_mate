### 메타데이터 스캔 시간 단축 - Local Media
  자막파일 등록을 위해서 LocalMedia 에이전트를 사용하지만 이 에이전트 안에 쓸데없이 비디오 파일에서 태그를 읽는 코드가 있다.  
  상당한 리소스를 사용하기 때문에 막는게 좋다.  

  PLEX MEDIA SERVER/Resources/Plug-ins-8dcc73a59/LocalMedia.bundle/Contents/Code/videohelpers.py 29라인
  ![](https://media.discordapp.net/attachments/631112094015815681/922381188709122068/unknown.png)

  ```return``` 추가

  Plug-ins-8dcc73a59 이는 버전에 따라 다르며 Plex 업데이트마다 수정해야 한다.

  [이런 문제도 해결](https://www.clien.net/service/board/cm_nas/14090027)

