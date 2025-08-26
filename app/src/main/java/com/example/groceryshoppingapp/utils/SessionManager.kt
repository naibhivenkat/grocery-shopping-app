package com.example.groceryshoppingapp.utils

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit

object SessionManager {
    private const val PREF_NAME = "GroceryAppSession"

    private const val KEY_USERNAME = "username"
    private const val KEY_ROLE = "role"
    private const val KEY_CUSTOMER_ID = "customer_id"
    private const val KEY_SHOPKEEPER_ID = "shopkeeper_id"
    private const val KEY_SHOP_ID = "shop_id"            // single shop UUID
    private const val KEY_SHOP_NAME = "shop_name"
    private const val KEY_PHOTO_BASE64 = "photo_base64"
    private const val KEY_SHOP_ITEMS = "shop_items"
    private const val KEY_HAS_ITEMS = "has_items_added"  // unified flag
    private const val KEY_SHOP_IDS = "shop_ids"          // multiple shop UUIDs

    // language
    private const val KEY_LANGUAGE_SELECTED = "language_selected"
    private const val KEY_LANGUAGE_CODE = "language_code"

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)

    // --- LOGIN & ROLE ---
    fun saveLogin(context: Context, username: String, role: String) {
        prefs(context).edit {
            putString(KEY_USERNAME, username)
                .putString(KEY_ROLE, role)
        }
    }

    fun getUsername(context: Context): String? = prefs(context).getString(KEY_USERNAME, null)
    fun getRole(context: Context): String? = prefs(context).getString(KEY_ROLE, null)

    // --- CUSTOMER & SHOPKEEPER IDs ---
    fun setCustomerId(context: Context, id: String) { prefs(context).edit().putString(KEY_CUSTOMER_ID, id).apply() }
    fun getCustomerId(context: Context): Int = prefs(context).getInt(KEY_CUSTOMER_ID, -1)

    fun setShopkeeperId(context: Context, id: String) { prefs(context).edit().putString(KEY_SHOPKEEPER_ID, id).apply() }
    fun getShopkeeperId(context: Context): Int = prefs(context).getInt(KEY_SHOPKEEPER_ID, -1)

    // --- SINGLE SHOP UUID ---

    fun setShopId(context: Context, shopId: String) {
        val sharedPreferences = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        val editor = sharedPreferences.edit()
        editor.putString(KEY_SHOP_ID, shopId) // ✅ save as String
        editor.apply()
    }

    fun getShopId(context: Context): String? {
        val sharedPreferences = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        return sharedPreferences.getString(KEY_SHOP_ID, null) // ✅ getString, not getInt
    }

    fun setShopInfo(context: Context, id: String?, name: String) {
        prefs(context).edit().putString(KEY_SHOP_ID, id).putString(KEY_SHOP_NAME, name).apply()
    }
    fun getShopName(context: Context): String? = prefs(context).getString(KEY_SHOP_NAME, null)

    // --- MULTIPLE SHOP UUIDs for SHOPKEEPER ---
    fun setShopIds(context: Context, shopIds: List<Int>) {
        val joined = shopIds.joinToString(",")
        prefs(context).edit().putString("shop_ids", joined).apply()
    }
    fun getShopIds(context: Context): List<Int> {
        val saved = prefs(context).getString("shop_ids", "") ?: ""
        return if (saved.isEmpty()) emptyList() else saved.split(",").mapNotNull { it.toIntOrNull() }
    }

    // --- PROFILE ---
    fun saveUserProfile(
        context: Context,
        fullName: String,
        address: String,
        phone: String,
        email: String,
        location: String,
        photoBase64: String?
    ) {
        prefs(context).edit()
            .putString("full_name", fullName)
            .putString("address", address)
            .putString("phone", phone)
            .putString("email", email)
            .putString("location", location)
            .putString(KEY_PHOTO_BASE64, photoBase64)
            .apply()
    }

    fun getPhotoBase64(context: Context): String? =
        prefs(context).getString(KEY_PHOTO_BASE64, null)?.takeIf { it.isNotBlank() && it != "null" }

    fun setPhotoBase64(context: Context, photoBase64: String) {
        prefs(context).edit().putString(KEY_PHOTO_BASE64, photoBase64).apply()
    }

    fun getFullName(context: Context): String? = prefs(context).getString("full_name", "")
    fun getAddress(context: Context): String? = prefs(context).getString("address", "")
    fun getPhone(context: Context): String? = prefs(context).getString("phone", "")
    fun getEmail(context: Context): String? = prefs(context).getString("email", "")
    fun getLocation(context: Context): String? = prefs(context).getString("location", "")

    // --- SHOP ITEMS ---
    fun setShopItems(context: Context, items: List<String>) {
        prefs(context).edit().putString(KEY_SHOP_ITEMS, items.joinToString("|")).apply()
        setHasItemsAdded(context, items.isNotEmpty())
    }
    fun getShopItems(context: Context): List<String> =
        prefs(context).getString(KEY_SHOP_ITEMS, null)?.split("|")?.filter { it.isNotBlank() } ?: emptyList()

    fun setHasItemsAdded(context: Context, added: Boolean) {
        prefs(context).edit().putBoolean(KEY_HAS_ITEMS, added).apply()
    }
    fun hasItemsAdded(context: Context): Boolean =
        prefs(context).getBoolean(KEY_HAS_ITEMS, false)

    // --- LOGOUT ---
    // funlogout(context: Context) { prefs(context).edit().clear().apply() }

    fun logout(context: Context) {
        val langSelected = isLanguageSelected(context)
        val langCode = getLanguageCode(context)

        prefs(context).edit().clear().apply()

        // restore language
        setLanguageSelected(context, langSelected)
        setLanguageCode(context, langCode ?: "en")
    }


    // --- LANGUAGE ---
    fun isLanguageSelected(context: Context): Boolean =
        prefs(context).getBoolean(KEY_LANGUAGE_SELECTED, false)

    fun setLanguageSelected(context: Context, selected: Boolean) {
        prefs(context).edit().putBoolean(KEY_LANGUAGE_SELECTED, selected).apply()
    }

    fun getLanguageCode(context: Context): String? =
        prefs(context).getString(KEY_LANGUAGE_CODE, "en")

    fun setLanguageCode(context: Context, code: String) {
        prefs(context).edit { putString(KEY_LANGUAGE_CODE, code) }
    }

    // --- LOGIN CHECK ---
    fun isLoggedIn(context: Context): Boolean {
        val username = getUsername(context)
        val role = getRole(context)
        return !username.isNullOrEmpty() && !role.isNullOrEmpty()
    }
}
