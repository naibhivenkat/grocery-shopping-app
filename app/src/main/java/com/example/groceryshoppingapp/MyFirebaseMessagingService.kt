package com.example.groceryshoppingapp

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.RingtoneManager
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Response
import retrofit2.Callback
class MyFirebaseMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        Log.d("FCM", "📩 Message received: ${remoteMessage.data}")

        val title = remoteMessage.notification?.title
            ?: remoteMessage.data["title"]
            ?: "Order Update"
        val message = remoteMessage.notification?.body
            ?: remoteMessage.data["message"]
            ?: "Your order status has changed"

        sendNotification(title, message)
    }


    override fun onNewToken(token: String) {
        super.onNewToken(token)

        Log.d("FCM", "New FCM token: $token")

        // Save token locally
        SessionManager.saveFcmToken(this, token)

        // Determine user role and ID
        val role = SessionManager.getRole(this)
        val userId = when (role) {
            "customer" -> SessionManager.getCustomerId(this)
            "shopkeeper" -> SessionManager.getShopkeeperId(this)
            else -> null
        }

        // If user is logged in, update backend
        if (!userId.isNullOrEmpty() && !role.isNullOrEmpty()) {

            val api = RetrofitClient.getInstance(this).create(ApiService::class.java)

            api.registerFcmToken(
                mapOf(
                    "user_id" to userId,
                    "role" to role,
                    "token" to token
                )
            ).enqueue(object : Callback<Map<String, Any>> {
                override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                    Log.d("FCM", "FCM token updated successfully")
                }

                override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                    Log.e("FCM", "Failed to update FCM token: ${t.message}")
                }
            })
        }
    }


    private fun sendNotification(title: String, messageBody: String) {
        val intent = Intent(this, CustomerHomeActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }

        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE
        )

        val channelId = "order_updates_channel"
        val defaultSoundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
        val notificationBuilder = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(R.drawable.ic_notification) // ✅ make sure you have this icon
            .setContentTitle(title)
            .setContentText(messageBody)
            .setAutoCancel(true)
            .setSound(defaultSoundUri)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_HIGH)

        val notificationManager =
            getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Order Updates",
                NotificationManager.IMPORTANCE_HIGH
            )
            notificationManager.createNotificationChannel(channel)
        }

        notificationManager.notify(System.currentTimeMillis().toInt(), notificationBuilder.build())
    }
}
