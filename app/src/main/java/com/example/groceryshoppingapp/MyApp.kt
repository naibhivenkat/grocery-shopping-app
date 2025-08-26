package com.example.groceryshoppingapp

import android.app.Application
import android.util.Log
import com.google.firebase.FirebaseApp

class MyApp : Application() {
    override fun onCreate() {
        super.onCreate()

        // Ensure Firebase is initialized
        if (FirebaseApp.getApps(this).isEmpty()) {
            FirebaseApp.initializeApp(this)
        }

        // Log Firebase apps for debugging
        for (app in FirebaseApp.getApps(this)) {
            Log.d("MyApp", "FirebaseApp: name=${app.name}, options=${app.options.applicationId}")
        }
    }
}
