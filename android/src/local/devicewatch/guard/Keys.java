package local.devicewatch.guard;
import android.content.*;
public class Keys extends BroadcastReceiver {
    public void onReceive(Context c, Intent i) {
        if ("local.devicewatch.guard.SET_MODE".equals(i.getAction())) {
            String request=i.getStringExtra("request");
            if (request==null || !request.matches("[a-f0-9]{32}") || !i.hasExtra("armed")) return;
            Guard.setMode(c,i.getBooleanExtra("armed",true),request);
            return;
        }
        String event=i.getStringExtra("event");
        if (Guard.armed(c) && java.util.Arrays.asList("power", "home", "back", "menu", "plug", "unplug", "test").contains(event))
            c.startForegroundService(new Intent(c, Guard.class).setAction(event)
                .putExtra("occurred_ms",i.getLongExtra("occurred_ms",System.currentTimeMillis()))
                .putExtra("kernel_us",i.getLongExtra("kernel_us",0)));
    }
}
