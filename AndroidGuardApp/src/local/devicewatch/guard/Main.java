package local.devicewatch.guard;
import android.app.Activity;
import android.content.*;
import android.os.Bundle;
import android.widget.*;

public class Main extends Activity {
    final SharedPreferences.OnSharedPreferenceChangeListener modeListener=(prefs,key)->{
        if("armed".equals(key))render();
    };
    private void render() {
        LinearLayout box=new LinearLayout(this); box.setOrientation(1); box.setPadding(32,48,32,16);
        TextView info=new TextView(this);
        info.setText(Guard.profile(this).optString("name","受控端")+" · "+(Guard.armed(this)?"已布防 · 心跳约两分钟一次":"已撤防"));
        box.addView(info);
        Button toggle=new Button(this); toggle.setText(Guard.armed(this)?"撤防":"布防"); box.addView(toggle);
        toggle.setOnClickListener(v->{
            boolean arm=!Guard.armed(this);
            Guard.setMode(this,arm,null);
        });
        Button test=new Button(this); test.setText("向服务端发送测试通知"); box.addView(test);
        test.setOnClickListener(v->startForegroundService(new Intent(this,Guard.class).setAction("test")));
        Button pin=new Button(this);pin.setText("设置或关闭第二层 PIN 锁");box.addView(pin);
        pin.setOnClickListener(v->{
            if(!android.provider.Settings.canDrawOverlays(this)){
                startActivity(new Intent(android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    android.net.Uri.parse("package:"+getPackageName())));return;
            }
            startForegroundService(new Intent(this,Guard.class).putExtra("pin_setup",true));
        });
        setContentView(box);
    }
    protected void onResume(){
        super.onResume();
        if (Guard.armed(this)||PinLock.enabled(this)) startForegroundService(new Intent(this,Guard.class));
        getSharedPreferences("guard",0).registerOnSharedPreferenceChangeListener(modeListener);
        render();
    }
    protected void onPause(){
        getSharedPreferences("guard",0).unregisterOnSharedPreferenceChangeListener(modeListener);
        super.onPause();
    }
}
