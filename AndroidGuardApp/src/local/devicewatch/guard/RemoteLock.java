package local.devicewatch.guard;

import android.content.*;
import android.os.SystemClock;
import java.io.*;
import java.security.*;
import java.util.*;
import javax.crypto.*;
import javax.crypto.spec.*;
import android.util.Base64;

public class RemoteLock extends BroadcastReceiver {
    private static final Map<String,String> challenges=new HashMap<>();
    private static final Map<String,Long> issued=new HashMap<>();
    public void onReceive(Context c,Intent i){
        if(!PinLock.enabled(c)){setResultData("disabled");return;}
        String host=i.getStringExtra("host"), op=i.getStringExtra("op");
        if(host==null || !host.matches("[0-9a-f]{32}"))return;
        File f=new File(c.getFilesDir(),"remote-"+host);
        if(!f.isFile())return;
        try{
            if("challenge".equals(op)){
                String nonce=UUID.randomUUID().toString();
                challenges.put(host,nonce);issued.put(host,SystemClock.elapsedRealtime());setResultData(nonce);return;
            }
            String nonce=challenges.remove(host);
            if(nonce==null || SystemClock.elapsedRealtime()-issued.remove(host)>10000)return;
            byte[] secret=java.nio.file.Files.readAllBytes(f.toPath());
            Mac m=Mac.getInstance("HmacSHA256");m.init(new SecretKeySpec(secret,"HmacSHA256"));
            if(!MessageDigest.isEqual(m.doFinal((host+"|"+op+"|"+nonce).getBytes("UTF-8")),Base64.decode(i.getStringExtra("proof"),0)))return;
            if(PinLock.active==null)c.startForegroundService(new Intent(c,Guard.class));
            if(PinLock.active==null)return;
            if("open".equals(op))PinLock.active.remote();
            else if("close".equals(op))PinLock.active.lock();else return;
            setResultData("ok");
        }catch(Exception ignored){}
    }
}
