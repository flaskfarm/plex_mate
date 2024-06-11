### 스캔 시간 단축 - Local Media
  자막파일 등록을 위해서 LocalMedia 에이전트를 사용하지만 이 에이전트 안에 쓸데없이 비디오 파일에서 태그를 읽는 코드가 있다.  
  상당한 리소스를 사용하기 때문에 막는게 좋다.  

  PLEX MEDIA SERVER/Resources/Plug-ins-8dcc73a59/LocalMedia.bundle/Contents/Code/videohelpers.py   

  서버 버전 1.40.2.8395 : /usr/lib/plexmediaserver/Resources/Plug-ins-c67dce28e/LocalMedia.bundle/Contents/Code/videohelpers.py

  ![](https://i.imgur.com/I9DPCfr.png)

  30라인 

  ```
  return
  ``` 추가

  Plug-ins-8dcc73a59 이는 Plex 버전에 따라 다르며 Plex 업데이트마다 수정해야 한다.

----
<br>

### Mixed content(혼합 콘텐츠) 문제로 인한 이미지 깨짐
브라우저 https 사이트에서 오래된 컨텐츠 검색시 http 이미지를 로딩할 때 이미지가 깨져 보임.   

URL : [http://cfile26.uf.daum.net/image/1248BF0F49A498AF3E882C](http://cfile26.uf.daum.net/image/1248BF0F49A498AF3E882C)

예: 목욕탕집 남자들    

<img src="https://i.imgur.com/bOBkkEN.png" width="70%">

사이트 설정 - 개인 정보 보호 및 보안 - 안전하지 않는 콘텐츠 허용

<img src="https://i.imgur.com/1DJHEL7.png" width="50%">

<img src="https://i.imgur.com/D8zaepq.png" width="70%">

----
<br>

