#!/system/bin/sh
until [ "$(getprop sys.boot_completed)" = 1 ]; do sleep 3; done
until [ "$(getprop sys.user.0.ce_available)" = true ]; do sleep 3; done
am start-foreground-service -n local.devicewatch.guard/.Guard >/dev/null

report() {
    am broadcast -n local.devicewatch.guard/.Keys --es event "$1" --el occurred_ms "$(date +%s%3N)" --el kernel_us "${2:-0}" >/dev/null
}

watch_keys() {
    while :; do
        power_node= navigation_node= fingerprint_node=
        for node in /sys/class/input/event*; do
            read -r name < "$node/device/name" || continue
            path="/dev/input/${node##*/}:"
            case "$name" in
                qpnp_pon) power_node=$path ;;
                synaptics_dsx) navigation_node=$path ;;
                uinput-goodix) fingerprint_node=$path ;;
            esac
        done
        # A terminal makes getevent flush each newline even when no other input follows.
        /data/adb/magisk/busybox script -q -c 'stty -onlcr; exec /system/bin/getevent -t 2>/dev/null' /dev/null |
        while IFS= read -r line; do
            case "$line" in *": 0001 "*" 00000001") ;; *) continue ;; esac
            clock=${line%%]*}
            clock=${clock#*[}
            set -- $clock
            clock=$1
            set -- ${line#*]}
            source=$1 type=$2 code=$3 value=$4
            [ "$type:$value" = '0001:00000001' ] || continue
            case "$source" in
                "$power_node"|"$fingerprint_node"|"$navigation_node") ;;
                *) continue ;;
            esac
            case "$code" in
                0074) event=power ;;
                0066) event=home ;;
                009e) event=back ;;
                008b) event=menu ;;
                *) continue ;;
            esac
            report "$event" "${clock%.*}${clock#*.}"
        done
        sleep 2
    done
}

watch_keys &
supply=/sys/class/power_supply
history=/data/adb/devicewatch-history
umask 077
mkdir -p "$history"
last_sample=
last_present=
while :; do
    if read -r present < "$supply/usb/present"; then
        case "$present" in
            0|1)
                case "$last_present:$present" in
                    1:0) report unplug ;;
                    0:1) report plug ;;
                esac
                last_present=$present
                ;;
        esac
    fi
    read -r level < "$supply/battery/capacity"
    read -r status < "$supply/battery/status"
    read -r suspended < "$supply/battery/input_suspend"
    sample="usb=$last_present battery=$level status=$status suspend=$suspended"
    if [ "$sample" != "$last_sample" ]; then
        log="$history/charge.log"
        if [ -f "$log" ] && [ "$(wc -c < "$log")" -gt 262144 ]; then
            mv "$log" "$log.1"
        fi
        echo "$(date '+%Y-%m-%d %H:%M:%S') $sample" >> "$log"
        last_sample=$sample
    fi
    sleep 1
done
