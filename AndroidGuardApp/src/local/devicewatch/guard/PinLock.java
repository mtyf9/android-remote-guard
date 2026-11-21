package local.devicewatch.guard;

import android.content.*;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.os.*;
import android.provider.Settings;
import android.view.*;
import android.widget.*;
import java.security.*;
import java.util.Arrays;
import javax.crypto.*;
import javax.crypto.spec.*;
import android.util.Base64;

final class PinLock {
    private final Guard guard;
    private final SharedPreferences prefs;
    private final WindowManager windows;
    private final Handler handler=new Handler();
    private LinearLayout panel;
    private String setup, first;
    private final StringBuilder digits=new StringBuilder();
    private TextView title, mask;
    static PinLock active;
    static boolean enabled(Context c){return c.getSharedPreferences("lock",0).contains("hash");}
    private final Runnable relock=this::lock;
    private final BroadcastReceiver screen=new BroadcastReceiver(){
        public void onReceive(Context c,Intent i){lock();}
    };
    PinLock(Guard g){
        guard=g; prefs=g.getSharedPreferences("lock",0); windows=g.getSystemService(WindowManager.class);
        active=this; g.registerReceiver(screen,new IntentFilter(Intent.ACTION_SCREEN_OFF)); lock();
    }
    boolean visible(){return panel!=null;}
    void lock(){
        handler.removeCallbacks(relock);
        if(enabled(guard)) show("unlock");
    }
    void remote(){
        if(!enabled(guard))return;
        hide(); handler.removeCallbacks(relock); handler.postDelayed(relock,30000);
    }
    void close(){guard.unregisterReceiver(screen); handler.removeCallbacks(relock); hide(); active=null;}
    void hide(){if(panel!=null){windows.removeViewImmediate(panel);panel=null;}digits.setLength(0);first=null;}
    private static String encode(byte[] b){return Base64.encodeToString(b,Base64.NO_WRAP);}
    private byte[] hash(String pin,byte[] salt) throws Exception{
        PBEKeySpec spec=new PBEKeySpec(pin.toCharArray(),salt,120000,256);
        try{return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();}
        finally{spec.clearPassword();}
    }
    void show(String mode){
        if(!Settings.canDrawOverlays(guard))return;
        hide(); setup=mode; panel=new LinearLayout(guard); panel.setOrientation(1);
        panel.setGravity(Gravity.CENTER); panel.setBackgroundColor(Color.BLACK);
        title=new TextView(guard);title.setTextColor(Color.WHITE);title.setTextSize(20);
        title.setText(mode.equals("set")?"设置 6 至 12 位 PIN":mode.equals("disable")?"输入 PIN 关闭第二层锁":"输入 PIN");
        title.setGravity(Gravity.CENTER);
        panel.addView(title);
        mask=new TextView(guard);
        mask.setGravity(Gravity.CENTER);mask.setTextColor(Color.WHITE);mask.setTextSize(22);
        mask.setMinLines(1);
        panel.addView(mask);
        for(String row:new String[]{"123","456","789","←0✓"}){
            LinearLayout line=new LinearLayout(guard);line.setGravity(Gravity.CENTER);panel.addView(line);
            for(char key:row.toCharArray()){
                Button b=new Button(guard);b.setBackgroundColor(Color.BLACK);b.setStateListAnimator(null);
                b.setSoundEffectsEnabled(false);b.setTextColor(Color.WHITE);b.setText(""+key);
                b.setFilterTouchesWhenObscured(true);b.setOnClickListener(v->press(key));line.addView(b);
            }
        }
        WindowManager.LayoutParams lp=new WindowManager.LayoutParams(-1,-1,WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_SECURE|WindowManager.LayoutParams.FLAG_FULLSCREEN,PixelFormat.OPAQUE);
        windows.addView(panel,lp);
    }
    private void press(char key){
        if(key!='✓'){
            if(key=='←'){if(digits.length()>0)digits.deleteCharAt(digits.length()-1);}
            else if(digits.length()<12)digits.append(key);
            mask.setText("************".substring(0,digits.length()));
            return;
        }
        String pin=digits.toString();digits.setLength(0);mask.setText("");
        try{
            if(setup.equals("set") && !enabled(guard)){
                if(pin.length()<6){title.setText("至少需要 6 位，请重新输入");return;}
                if(first==null){first=pin;title.setText("再次输入 PIN");return;}
                if(!first.equals(pin)){first=null;title.setText("两次不同，请重新设置");return;}
                byte[] salt=new byte[16];new SecureRandom().nextBytes(salt);
                if(prefs.edit().putString("salt",encode(salt)).putString("hash",encode(hash(pin,salt))).commit())lock();
                return;
            }
            if(System.currentTimeMillis()<prefs.getLong("retry",0)){title.setText("请稍后重试");return;}
            boolean ok=MessageDigest.isEqual(Base64.decode(prefs.getString("hash",""),0),
                hash(pin,Base64.decode(prefs.getString("salt",""),0)));
            if(!ok){
                int failures=Math.min(8,prefs.getInt("fails",0)+1);
                prefs.edit().putInt("fails",failures).putLong("retry",System.currentTimeMillis()+(1000L<<failures)).commit();
                guard.event("pin_error",System.currentTimeMillis());title.setText("PIN 错误，请稍后重试");return;
            }
            SharedPreferences.Editor edit=prefs.edit().remove("retry").remove("fails");
            if(setup.equals("disable"))edit.remove("hash").remove("salt");
            edit.commit();hide();
        }catch(Exception ex){title.setText("无法验证 PIN");}
    }
}
