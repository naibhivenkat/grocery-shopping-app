package com.example.groceryshoppingapp.network

import android.content.Context
import com.example.groceryshoppingapp.utils.SessionManager
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

object RetrofitClient {

    private const val BASE_URL = "https://grocery-shopping-app-yyqx.onrender.com/"

    // Call this with a Context so token can be read from SessionManager
    fun getInstance(context: Context): Retrofit {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }

        val client = OkHttpClient.Builder()
            // ✅ Add token automatically
            .addInterceptor { chain ->
                val original: Request = chain.request()
                val builder = original.newBuilder()

                val token = SessionManager.getAuthToken(context)
                if (!token.isNullOrEmpty()) {
                    builder.addHeader("Authorization", "Bearer $token")
                }

                chain.proceed(builder.build())
            }
            .addInterceptor(logging)
            .build()

        return Retrofit.Builder()
            .baseUrl(BASE_URL)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
    }
}
