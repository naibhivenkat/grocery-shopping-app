package com.example.groceryshoppingapp

import android.content.Context
import java.util.Locale

object LanguageManager {
    fun applySavedLanguage(context: Context) {
        val code = com.example.groceryshoppingapp.utils.SessionManager.getLanguageCode(context) ?: "en"
        context.applyLanguage(code)
    }
}

fun Context.applyLanguage(langCode: String) {
    val locale = Locale(langCode)
    Locale.setDefault(locale)
    val config = resources.configuration
    config.setLocale(locale)
    @Suppress("DEPRECATION")
    resources.updateConfiguration(config, resources.displayMetrics)
}
