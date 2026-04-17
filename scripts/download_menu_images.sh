#!/usr/bin/env bash
# One-shot download of all Wikimedia menu images to the client's public dir.
# Uses a descriptive User-Agent per Wikimedia's hotlinking policy.
set -euo pipefail

OUT="$(cd "$(dirname "$0")/../../client/public/images/menu" && pwd)"
UA="SaffronAndSmoke/1.0 (https://saffronandsmoke.example; contact@example.com)"

download() {
    local id="$1" url="$2"
    local ext="${url##*.}"
    # strip url query/frag if any
    ext="${ext%%\?*}"
    # normalize JPG/JPEG → jpg
    case "$ext" in
        JPG|JPEG|jpeg) ext="jpg" ;;
    esac
    local dest="$OUT/$id.$ext"
    if [[ -s "$dest" ]]; then
        echo "   $id already exists → $dest"
        return
    fi
    echo "⇩  $id ← $url"
    curl -sSL -A "$UA" -o "$dest" "$url"
    [[ -s "$dest" ]] || { echo "FAILED: $id"; rm -f "$dest"; exit 1; }
}

download S01 "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/Paneer_tikka.jpg/640px-Paneer_tikka.jpg"
download S02 "https://upload.wikimedia.org/wikipedia/commons/thumb/8/88/Tunday_Kebabs.jpg/640px-Tunday_Kebabs.jpg"
download S03 "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/Crispy_deep-fried_prawn_of_Ulakan.JPG/640px-Crispy_deep-fried_prawn_of_Ulakan.JPG"
download S04 "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a6/Homemade_Beetroot_Hummus.jpg/640px-Homemade_Beetroot_Hummus.jpg"
download M01 "https://upload.wikimedia.org/wikipedia/commons/thumb/4/41/Butter_Chicken_%26_Butter_Naan_-_Home_-_Chandigarh_-_India_-_0006.jpg/640px-Butter_Chicken_%26_Butter_Naan_-_Home_-_Chandigarh_-_India_-_0006.jpg"
download M02 "https://upload.wikimedia.org/wikipedia/commons/thumb/6/67/Rogan_Josh_Kashmiri.jpg/640px-Rogan_Josh_Kashmiri.jpg"
download M03 "https://upload.wikimedia.org/wikipedia/commons/thumb/6/69/Punjabi_style_Dal_Makhani.jpg/640px-Punjabi_style_Dal_Makhani.jpg"
download M04 "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7c/Hyderabadi_Chicken_Biryani.jpg/640px-Hyderabadi_Chicken_Biryani.jpg"
download M05 "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/Paneer_tikka_lababdar.JPG/640px-Paneer_tikka_lababdar.JPG"
download M06 "https://upload.wikimedia.org/wikipedia/commons/thumb/2/26/Sea_bass_fillet_at_the_White_Hart_Inn%2C_Moreton%2C_Essex%2C_England.jpg/640px-Sea_bass_fillet_at_the_White_Hart_Inn%2C_Moreton%2C_Essex%2C_England.jpg"
download B01 "https://upload.wikimedia.org/wikipedia/commons/thumb/9/98/Butter_Naan_Flatbread_from_North_India.jpg/640px-Butter_Naan_Flatbread_from_North_India.jpg"
download B02 "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0d/Garlic_Naan.JPG/640px-Garlic_Naan.JPG"
download B03 "https://upload.wikimedia.org/wikipedia/commons/thumb/7/70/Laccha_Paratha.JPG/640px-Laccha_Paratha.JPG"
download B04 "https://upload.wikimedia.org/wikipedia/commons/thumb/4/41/Tandoori_Roti.JPG/640px-Tandoori_Roti.JPG"
download B05 "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ad/Cheese_Naan.jpg/640px-Cheese_Naan.jpg"
download R01 "https://upload.wikimedia.org/wikipedia/commons/thumb/3/36/Cooked_cilantro_lime_dish_basmati_rice_India.jpg/640px-Cooked_cilantro_lime_dish_basmati_rice_India.jpg"
download R02 "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5e/Jeera-rice.JPG/640px-Jeera-rice.JPG"
download R03 "https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Zafrani_Pulao.jpg/640px-Zafrani_Pulao.jpg"
download D01 "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0f/Bowl_of_Gulab_Jamuns.jpg/640px-Bowl_of_Gulab_Jamuns.jpg"
download D02 "https://upload.wikimedia.org/wikipedia/commons/thumb/0/05/Brownie_with_ice_cream.jpg/640px-Brownie_with_ice_cream.jpg"
download D03 "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7a/Firni_Or_Phirni.jpg/640px-Firni_Or_Phirni.jpg"
download BV01 "https://upload.wikimedia.org/wikipedia/commons/thumb/8/89/Chai_In_Sakora.jpg/640px-Chai_In_Sakora.jpg"
download BV02 "https://upload.wikimedia.org/wikipedia/commons/thumb/8/81/Nimbu_pani.JPG/640px-Nimbu_pani.JPG"
download BV03 "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5b/Mango_Lassi_made_out_of_Mango_pulp_and_Milk.JPG/640px-Mango_Lassi_made_out_of_Mango_pulp_and_Milk.JPG"
download BV04 "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0f/Rooh_Afza_%28Sharbat%29.JPG/640px-Rooh_Afza_%28Sharbat%29.JPG"
download BV05 "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6c/Homemade_Cold_Coffee%28Indian_Style%29-_Kolkata.jpg/640px-Homemade_Cold_Coffee%28Indian_Style%29-_Kolkata.jpg"
download BV06 "https://upload.wikimedia.org/wikipedia/commons/thumb/0/02/Stilles_Mineralwasser.jpg/640px-Stilles_Mineralwasser.jpg"

echo
echo "All images downloaded to $OUT"
ls -1 "$OUT"
